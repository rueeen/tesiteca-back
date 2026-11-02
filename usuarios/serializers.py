from django.conf import settings
from rest_framework import serializers
from .models import Usuario, UsuarioAutorizado, Rol


class CorreoSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.strip().lower()
        if value.rsplit("@", 1)[-1] not in settings.ALLOWED_EMAIL_DOMAINS:
            raise serializers.ValidationError("El correo debe ser institucional")
        return value


class CodigoSerializer(CorreoSerializer):
    codigo = serializers.RegexField(r"^\d{6}$")


class UsuarioSerializer(serializers.ModelSerializer):
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
