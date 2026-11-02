from django.conf import settings
from rest_framework import serializers
from .models import Usuario, UsuarioAutorizado, Rol
from academico.serializers import CarreraMiniSerializer, MiniSerializer


class CorreoSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.strip().lower()
        if value.rsplit("@", 1)[-1] not in settings.ALLOWED_EMAIL_DOMAINS:
            raise serializers.ValidationError("El correo debe ser institucional")
        return value


class CodigoSerializer(CorreoSerializer):
    codigo = serializers.RegexField(r"^\d{6}$")


class UsuarioMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["id", "nombre_completo", "email"]


class UsuarioSerializer(serializers.ModelSerializer):
    carrera = CarreraMiniSerializer(read_only=True)
    area = MiniSerializer(read_only=True)
    sede = MiniSerializer(read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "email",
            "rut",
            "nombre_completo",
            "rol",
            "carrera",
            "area",
            "sede",
        ]


class AutorizadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsuarioAutorizado
        fields = [
            "id",
            "email",
            "rut",
            "nombre_completo",
            "rol",
            "carrera",
            "area",
            "sede",
            "activo",
        ]

    def to_representation(self, instancia):
        datos = super().to_representation(instancia)
        for campo, serializador in [
            ("carrera", CarreraMiniSerializer),
            ("area", MiniSerializer),
            ("sede", MiniSerializer),
        ]:
            valor = getattr(instancia, campo)
            datos[campo] = serializador(valor).data if valor is not None else None
        return datos

    def validate_email(self, value):
        return CorreoSerializer().validate_email(value)

    def validate(self, datos):
        rol = datos.get("rol", getattr(self.instance, "rol", None))
        carrera = datos.get("carrera", getattr(self.instance, "carrera", None))
        area = datos.get("area", getattr(self.instance, "area", None))
        if rol in (Rol.ESTUDIANTE, Rol.COORDINADOR) and not carrera:
            raise serializers.ValidationError("La carrera es obligatoria")
        if rol == Rol.DIRECTOR and not area:
            raise serializers.ValidationError("El área es obligatoria para directores")
        if carrera and area and carrera.area_id != area.id:
            raise serializers.ValidationError("La carrera no corresponde al área")
        return datos
