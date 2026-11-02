import json
import re
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from rest_framework import serializers
from usuarios.models import Rol
from .models import Tesis, AutorTesis, MaterialAdicional
from .permisos import material_visible
from .servicios import guardar_tesis

REPOSITORIO = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/?$")


def validar_repositorio(url, carrera):
    if not carrera.permite_repositorio:
        raise serializers.ValidationError("Esta carrera no permite repositorios")
    if not REPOSITORIO.fullmatch(url):
        raise serializers.ValidationError("Usa una URL de repositorio GitHub válida")
    return url


class AutorSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutorTesis
        fields = ["nombre_completo", "email"]


class MaterialSerializer(serializers.ModelSerializer):
    archivo = serializers.FileField(write_only=True, required=False)
    restringido = serializers.SerializerMethodField()

    class Meta:
        model = MaterialAdicional
        fields = [
            "id",
            "tipo",
            "titulo",
            "descripcion",
            "url",
            "archivo",
            "solo_carrera",
            "creado",
            "restringido",
        ]
        read_only_fields = ["id", "creado"]

    def get_restringido(self, obj):
        return not material_visible(self.context["request"].user, obj)

    def to_representation(self, obj):
        datos = super().to_representation(obj)
        if datos["restringido"]:
            datos.pop("url", None)
        elif obj.tipo == "ARCHIVO":
            datos["descarga"] = f"/api/materiales/{obj.id}/descargar/"
        return datos

    def validate(self, datos):
        tesis = self.context["tesis"]
        tipo = datos.get("tipo")
        url = datos.get("url", "")
        archivo = datos.get("archivo")
        if tipo == "REPOSITORIO":
            validar_repositorio(url, tesis.carrera)
            datos["solo_carrera"] = True
        elif tipo == "ENLACE":
            if urlparse(url).scheme != "https" or not urlparse(url).hostname:
                raise serializers.ValidationError("El enlace debe usar HTTPS")
        elif tipo == "ARCHIVO":
            if not archivo:
                raise serializers.ValidationError("El archivo es obligatorio")
            extensiones = {
                e.strip().lower() for e in tesis.carrera.extensiones_material.split(",")
            }
            if Path(archivo.name).suffix.lower() not in extensiones:
                raise serializers.ValidationError("Extensión no permitida")
            if archivo.size > settings.MAX_MATERIAL_MB * 1024 * 1024:
                raise serializers.ValidationError("El material supera el tamaño máximo")
        if tipo != "ARCHIVO" and archivo:
            raise serializers.ValidationError("Este tipo no admite archivo")
        if tipo == "ARCHIVO" and url:
            raise serializers.ValidationError("Un archivo no admite URL")
        return datos


class TesisListaSerializer(serializers.ModelSerializer):
    autores = serializers.SerializerMethodField()
    carrera = serializers.CharField(source="carrera.nombre")
    resumen = serializers.SerializerMethodField()
    palabras_clave = serializers.SerializerMethodField()
    tiene_repositorio = serializers.SerializerMethodField()

    class Meta:
        model = Tesis
        fields = [
            "id",
            "titulo",
            "resumen",
            "autores",
            "carrera",
            "anio",
            "tipo",
            "profesor_guia",
            "palabras_clave",
            "num_paginas",
            "tiene_repositorio",
        ]

    def get_autores(self, obj):
        return [a.nombre_completo for a in obj.autores.all()]

    def get_resumen(self, obj):
        return obj.resumen[:280]

    def get_palabras_clave(self, obj):
        return [p.strip() for p in obj.palabras_clave.split(",") if p.strip()]

    def get_tiene_repositorio(self, obj):
        return any(m.tipo == "REPOSITORIO" for m in obj.materiales.all())


class TesisDetalleSerializer(serializers.ModelSerializer):
    autores = AutorSerializer(many=True, read_only=True)
    materiales = MaterialSerializer(many=True, read_only=True)
    pdf = serializers.SerializerMethodField()

    class Meta:
        model = Tesis
        fields = [
            "id",
            "titulo",
            "resumen",
            "palabras_clave",
            "tipo",
            "anio",
            "semestre",
            "carrera",
            "sede",
            "profesor_guia",
            "estado",
            "observacion_revision",
            "subido_por",
            "revisado_por",
            "fecha_publicacion",
            "num_paginas",
            "tamano_bytes",
            "creado",
            "actualizado",
            "autores",
            "materiales",
            "pdf",
        ]

    def get_pdf(self, obj):
        return f"/api/tesis/{obj.id}/pdf/"


class AutoresJSON(serializers.Field):
    def to_internal_value(self, valor):
        try:
            valor = json.loads(valor) if isinstance(valor, str) else valor
        except (ValueError, TypeError):
            raise serializers.ValidationError("Autores debe ser JSON válido")
        serial = AutorSerializer(data=valor, many=True)
        serial.is_valid(raise_exception=True)
        return serial.validated_data

    def to_representation(self, valor):
        return AutorSerializer(valor, many=True).data


class TesisEscrituraSerializer(serializers.ModelSerializer):
    pdf = serializers.FileField(write_only=True, required=False)
    autores = AutoresJSON(write_only=True, required=False)
    repositorio_url = serializers.URLField(
        write_only=True, required=False, allow_blank=True
    )
    publicar = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Tesis
        fields = [
            "titulo",
            "resumen",
            "palabras_clave",
            "tipo",
            "anio",
            "semestre",
            "carrera",
            "sede",
            "profesor_guia",
            "pdf",
            "autores",
            "repositorio_url",
            "publicar",
        ]

    def validate(self, datos):
        usuario = self.context["request"].user
        carrera = datos.get("carrera", getattr(self.instance, "carrera", None))
        sede = datos.get("sede", getattr(self.instance, "sede", None))
        if not self.instance and "pdf" not in datos:
            raise serializers.ValidationError("El PDF es obligatorio")
        if not self.instance:
            datos.setdefault("autores", [])
        if not carrera or not carrera.activa or not sede or not sede.activa:
            raise serializers.ValidationError("Selecciona carrera y sede activas")
        if (
            usuario.rol in (Rol.ESTUDIANTE, Rol.COORDINADOR)
            and usuario.carrera_id != carrera.id
        ):
            raise serializers.ValidationError("Solo puedes subir a tu carrera")
        if usuario.rol == Rol.DIRECTOR and usuario.area_id != carrera.area_id:
            raise serializers.ValidationError("Solo puedes subir a tu área")
        if datos.get("repositorio_url"):
            validar_repositorio(datos["repositorio_url"], carrera)
        if self.instance and carrera.pk != self.instance.carrera_id:
            raise serializers.ValidationError(
                "No puedes cambiar la carrera de una tesis existente"
            )
        return datos

    def create(self, datos):
        return guardar_tesis(datos, self.context["request"].user)

    def update(self, instancia, datos):
        return guardar_tesis(datos, self.context["request"].user, instancia)
