from django.conf import settings
from rest_framework import serializers
from .models import Usuario, UsuarioAutorizado, Rol, SolicitudAcceso
from academico.serializers import (
    CarreraMiniSerializer,
    MiniSerializer,
    SedeMiniSerializer,
)


class CorreoSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.strip().lower()
        if value.rsplit("@", 1)[-1] not in settings.ALLOWED_EMAIL_DOMAINS:
            raise serializers.ValidationError("El correo debe ser institucional")
        return value


class UsuarioMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["id", "nombre_completo", "email"]


class UsuarioSerializer(serializers.ModelSerializer):
    carrera = CarreraMiniSerializer(read_only=True)
    area = MiniSerializer(read_only=True)
    sede = SedeMiniSerializer(read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "email",
            "rut",
            "nombre_completo",
            "rol",
            "estado_cuenta",
            "carrera",
            "area",
            "sede",
        ]


class AutorizadoSerializer(serializers.ModelSerializer):
    estado_cuenta = serializers.CharField(read_only=True, allow_null=True)

    def validate_rut(self, valor):
        if not valor.strip():
            return ""
        try:
            return normalizar_rut(valor)
        except ErrorDjango as exc:
            raise serializers.ValidationError(exc.messages)

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
            "estado_cuenta",
        ]

    def to_representation(self, instancia):
        datos = super().to_representation(instancia)
        if not hasattr(instancia, "estado_cuenta"):
            datos["estado_cuenta"] = (
                Usuario.objects.filter(email=instancia.email)
                .values_list("estado_cuenta", flat=True)
                .first()
            )
        for campo, serializador in [
            ("carrera", CarreraMiniSerializer),
            ("area", MiniSerializer),
            ("sede", SedeMiniSerializer),
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
        sede = datos.get("sede", getattr(self.instance, "sede", None))
        if rol != Rol.ADMIN and not sede:
            raise serializers.ValidationError({"sede": "La sede es obligatoria"})
        email = datos.get("email", getattr(self.instance, "email", ""))
        if (
            rol in (Rol.COORDINADOR, Rol.DIRECTOR)
            and (
                self.instance is None
                or rol != self.instance.rol
                or email != self.instance.email
            )
            and not email.endswith("@inacap.cl")
        ):
            raise serializers.ValidationError(
                {"email": "Los funcionarios deben usar correo @inacap.cl"}
            )
        if rol in (Rol.ESTUDIANTE, Rol.COORDINADOR) and carrera:
            if "area" in datos and area and area.pk != carrera.area_id:
                raise serializers.ValidationError(
                    {"area": "La carrera no corresponde al área"}
                )
            datos["area"] = carrera.area
            area = carrera.area
        if rol == Rol.DIRECTOR:
            datos["carrera"] = None
            carrera = None
        if carrera and area and carrera.area_id != area.id:
            raise serializers.ValidationError("La carrera no corresponde al área")
        return datos


from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as ErrorDjango
from academico.models import Carrera, Sede
from .validacion import normalizar_rut


class RegistroSerializer(CorreoSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password2 = serializers.CharField(write_only=True, trim_whitespace=False)
    nombre_completo = serializers.CharField(max_length=200)
    rut = serializers.CharField(max_length=20)
    carrera = serializers.PrimaryKeyRelatedField(
        queryset=Carrera.objects.filter(activa=True), required=False, allow_null=True
    )
    sede = serializers.PrimaryKeyRelatedField(queryset=Sede.objects.filter(activa=True))
    rol_solicitado = serializers.ChoiceField(
        choices=[Rol.ESTUDIANTE, Rol.COORDINADOR, Rol.DIRECTOR], required=False
    )
    mensaje = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    def validate_rut(self, valor):
        try:
            return normalizar_rut(valor)
        except ErrorDjango as exc:
            raise serializers.ValidationError(exc.messages)

    def validate(self, datos):
        dominio = datos["email"].rsplit("@", 1)[1]
        autorizado = (
            UsuarioAutorizado.objects.select_related("carrera", "area", "sede")
            .filter(email=datos["email"], activo=True)
            .first()
        )
        if autorizado:
            datos.update(
                rol_solicitado=autorizado.rol,
                carrera=autorizado.carrera,
                area=autorizado.area,
                sede=autorizado.sede,
            )
        rol = datos.get(
            "rol_solicitado",
            Rol.ESTUDIANTE if dominio == "inacapmail.cl" else Rol.COORDINADOR,
        )
        if dominio == "inacapmail.cl" and rol != Rol.ESTUDIANTE:
            raise serializers.ValidationError(
                {"rol_solicitado": "Los estudiantes solo pueden solicitar ESTUDIANTE"}
            )
        if (
            dominio == "inacap.cl"
            and rol not in (Rol.COORDINADOR, Rol.DIRECTOR)
            and not (autorizado and rol == Rol.ADMIN)
        ):
            raise serializers.ValidationError(
                {"rol_solicitado": "Solicita COORDINADOR o DIRECTOR"}
            )
        if dominio not in ("inacapmail.cl", "inacap.cl"):
            raise serializers.ValidationError(
                {"email": "El correo debe ser institucional"}
            )
        if rol in (Rol.ESTUDIANTE, Rol.COORDINADOR) and not datos.get("carrera"):
            raise serializers.ValidationError({"carrera": "La carrera es obligatoria"})
        if datos["password"] != datos["password2"]:
            raise serializers.ValidationError(
                {"password2": "Las contraseñas no coinciden"}
            )
        usuario = Usuario(
            email=datos["email"], nombre_completo=datos["nombre_completo"]
        )
        try:
            validate_password(datos["password"], usuario)
        except ErrorDjango as exc:
            raise serializers.ValidationError({"password": exc.messages})
        if (
            Usuario.objects.filter(rut=datos["rut"])
            .exclude(email=datos["email"])
            .exists()
        ):
            raise serializers.ValidationError({"rut": "Este RUT ya está registrado"})
        datos["rol_solicitado"] = rol
        return datos


class SolicitanteSerializer(UsuarioMiniSerializer):
    class Meta(UsuarioMiniSerializer.Meta):
        fields = ["id", "email", "nombre_completo", "rut"]


class SolicitudSerializer(serializers.ModelSerializer):
    correo_validado = serializers.SerializerMethodField()
    estado_cuenta = serializers.CharField(
        source="usuario.estado_cuenta", read_only=True
    )

    def get_correo_validado(self, obj):
        return obj.usuario.email_verificado_en is not None

    usuario = SolicitanteSerializer(read_only=True)
    carrera = CarreraMiniSerializer(read_only=True)
    sede = SedeMiniSerializer(read_only=True)
    revisada_por = UsuarioMiniSerializer(read_only=True)
    puede_cambiar_rol = serializers.SerializerMethodField()

    class Meta:
        model = SolicitudAcceso
        fields = [
            "id",
            "usuario",
            "rol_solicitado",
            "carrera",
            "sede",
            "mensaje",
            "estado",
            "motivo_rechazo",
            "creada",
            "revisada_por",
            "revisada_en",
            "puede_cambiar_rol",
            "correo_validado",
            "estado_cuenta",
        ]

    def get_puede_cambiar_rol(self, obj):
        return self.context["request"].user.rol == Rol.ADMIN
