from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from academico.models import Carrera, Area, Sede
from .models import Usuario, UsuarioAutorizado, Rol, EstadoCuenta
from .serializers import AutorizadoSerializer
from .validacion import normalizar_rut
from django.core.exceptions import ValidationError as ErrorDjango
from .cuentas import aprobar_cuenta, revocar_sesiones


class GestionaFuncionarios(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol in (
            Rol.ADMIN,
            Rol.DIRECTOR,
        )


def en_ambito(usuario, datos):
    if usuario.rol == Rol.ADMIN:
        return True
    carrera = datos.get("carrera")
    sede = datos.get("sede")
    return bool(
        datos.get("rol") == Rol.COORDINADOR
        and carrera
        and sede
        and carrera.area_id == usuario.area_id
        and sede.pk == usuario.sede_id
    )


class FuncionarioSerializer(serializers.Serializer):
    email = serializers.EmailField()
    nombre_completo = serializers.CharField(max_length=200)
    rut = serializers.CharField(max_length=20, required=False, allow_blank=True)
    rol = serializers.ChoiceField(choices=[Rol.COORDINADOR, Rol.DIRECTOR])
    carrera = serializers.PrimaryKeyRelatedField(
        queryset=Carrera.objects.filter(activa=True, area__activa=True),
        required=False,
        allow_null=True,
    )
    area = serializers.PrimaryKeyRelatedField(
        queryset=Area.objects.filter(activa=True), required=False, allow_null=True
    )
    sede = serializers.PrimaryKeyRelatedField(queryset=Sede.objects.filter(activa=True))

    def validate_email(self, valor):
        valor = valor.strip().lower()
        if not valor.endswith("@inacap.cl"):
            raise serializers.ValidationError(
                "Los funcionarios deben usar correo @inacap.cl"
            )
        return valor

    def validate_rut(self, valor):
        if not valor:
            return ""
        try:
            return normalizar_rut(valor)
        except ErrorDjango as exc:
            raise serializers.ValidationError(exc.messages)

    def validate(self, datos):
        if datos["rol"] == Rol.COORDINADOR:
            if not datos.get("carrera"):
                raise serializers.ValidationError(
                    {"carrera": "La carrera es obligatoria para coordinadores"}
                )
            datos["area"] = datos["carrera"].area
        else:
            if not datos.get("area"):
                raise serializers.ValidationError(
                    {"area": "El área es obligatoria para directores"}
                )
            if datos.get("carrera"):
                raise serializers.ValidationError(
                    {"carrera": "El director no tiene carrera asignada"}
                )
            datos["carrera"] = None
        return datos


class Funcionarios(APIView):
    permission_classes = [GestionaFuncionarios]

    @transaction.atomic
    def post(self, request):
        if (
            request.user.rol == Rol.DIRECTOR
            and request.data.get("rol") != Rol.COORDINADOR
        ):
            raise PermissionDenied("Solo puedes registrar coordinadores")
        serial = FuncionarioSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        datos = serial.validated_data
        if not en_ambito(request.user, datos):
            raise PermissionDenied("Funcionario fuera de tu área o sede")
        autorizado = (
            UsuarioAutorizado.objects.select_for_update()
            .filter(email=datos["email"])
            .first()
        )
        cuenta = (
            Usuario.objects.select_for_update().filter(email=datos["email"]).first()
        )
        for existente in [autorizado, cuenta]:
            if existente:
                if existente.rol == Rol.ADMIN:
                    raise ValidationError("Los ADMIN se gestionan con crear_admin")
                if not en_ambito(
                    request.user,
                    {c: getattr(existente, c) for c in ["rol", "carrera", "sede"]},
                ):
                    raise PermissionDenied(
                        "No puedes modificar un funcionario fuera de tu ámbito"
                    )
        anterior = cuenta.rol if cuenta else None
        defaults = {k: v for k, v in datos.items() if k != "email"}
        if "rut" not in defaults:
            defaults["rut"] = (
                autorizado.rut if autorizado else cuenta.rut if cuenta else ""
            )
        defaults["activo"] = True
        autorizado, _ = UsuarioAutorizado.objects.update_or_create(
            email=datos["email"], defaults=defaults
        )
        if cuenta:
            if anterior != datos["rol"]:
                revocar_sesiones(cuenta)
            aprobar_cuenta(cuenta, datos, revisor=request.user)
            siguiente = (
                "Puede iniciar sesión con su contraseña."
                if cuenta.estado_cuenta == EstadoCuenta.ACTIVA
                else "Debe validar su correo antes de ingresar."
            )
        else:
            siguiente = (
                "Pídele que entre a Solicitar acceso con su correo institucional"
            )
        autorizado.refresh_from_db()
        if any(getattr(autorizado, k) != v for k, v in defaults.items()):
            for campo, valor in defaults.items():
                setattr(autorizado, campo, valor)
            autorizado.save()
        return Response(
            {
                "autorizado": AutorizadoSerializer(autorizado).data,
                "cuenta": (
                    {"existe": True, "estado_cuenta": cuenta.estado_cuenta}
                    if cuenta
                    else None
                ),
                "siguiente_paso": siguiente,
            },
            status=201,
        )
