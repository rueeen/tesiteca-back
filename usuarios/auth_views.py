import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError as ErrorDjango
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from config.throttling import ThrottleIP
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from tesis.views import ip_cliente
from .models import (
    Usuario,
    UsuarioAutorizado,
    SolicitudAcceso,
    IntentoLogin,
    EstadoCuenta,
    Rol,
)
from .serializers import RegistroSerializer, CorreoSerializer, UsuarioSerializer
from .cookies import poner_refresh
from .cuentas import (
    enviar_verificacion,
    enviar_correo,
    aprobar_cuenta,
    avisar_solicitud,
    revocar_sesiones,
    sello_verificacion,
    SAL_VERIFICACION,
    puede_iniciar_sesion,
    sincronizar_autorizado,
)

GENERICO_REGISTRO = (
    "Si los datos son válidos, te enviamos un correo para validar tu cuenta."
)
GENERICO_CORREO = (
    "Si la cuenta cumple los requisitos, recibirás un correo con instrucciones."
)
ENLACE_INVALIDO = "El enlace ya fue usado o venció. Solicita uno nuevo."
HASH_FICTICIO = make_password(secrets.token_urlsafe(32))


class Publica(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ThrottleIP]
    throttle_scope = "cuentas"


class Registro(Publica):
    throttle_scope = "registro"

    @transaction.atomic
    def post(self, request):
        serial = RegistroSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        datos = serial.validated_data
        usuario = (
            Usuario.objects.select_for_update().filter(email=datos["email"]).first()
        )
        if usuario and usuario.estado_cuenta not in (
            EstadoCuenta.PENDIENTE_VERIFICACION,
            EstadoCuenta.RECHAZADA,
        ):
            return Response({"detail": GENERICO_REGISTRO}, status=201)
        if usuario and usuario.estado_cuenta == EstadoCuenta.PENDIENTE_VERIFICACION:
            from privacidad.servicios import aceptar_politica

            aceptar_politica(usuario)
            enviar_verificacion(usuario)
            return Response({"detail": GENERICO_REGISTRO}, status=201)
        rechazada = usuario is not None
        usuario = usuario or Usuario(email=datos["email"])
        for campo in ["nombre_completo", "rut", "carrera", "sede", "area"]:
            setattr(usuario, campo, datos.get(campo))
        usuario.rol = datos["rol_solicitado"]
        usuario.estado_cuenta = (
            EstadoCuenta.PENDIENTE_APROBACION
            if rechazada
            else EstadoCuenta.PENDIENTE_VERIFICACION
        )
        usuario.set_password(datos["password"])
        try:
            with transaction.atomic():
                usuario.save()
        except IntegrityError:
            raise ValidationError({"rut": "El correo o RUT ya está registrado"})
        from privacidad.servicios import aceptar_politica

        aceptar_politica(usuario)
        solicitud, _ = SolicitudAcceso.objects.update_or_create(
            usuario=usuario,
            defaults={
                "rol_solicitado": datos["rol_solicitado"],
                "carrera": datos.get("carrera"),
                "sede": datos["sede"],
                "mensaje": datos.get("mensaje", ""),
                "estado": "PENDIENTE",
                "motivo_rechazo": "",
                "revisada_por": None,
                "revisada_en": None,
            },
        )
        if rechazada:
            avisar_solicitud(solicitud)
        else:
            enviar_verificacion(usuario)
        return Response({"detail": GENERICO_REGISTRO}, status=201)


class VerificarCorreo(Publica):
    @transaction.atomic
    def post(self, request):
        try:
            datos = signing.loads(
                request.data.get("token", ""), salt=SAL_VERIFICACION, max_age=48 * 3600
            )
            usuario = Usuario.objects.select_for_update().get(pk=datos["id"])
            if (
                usuario.email_verificado_en
                or usuario.estado_cuenta != EstadoCuenta.PENDIENTE_VERIFICACION
                or not secrets.compare_digest(
                    datos["sello"], sello_verificacion(usuario)
                )
            ):
                raise ValueError
        except (
            signing.BadSignature,
            Usuario.DoesNotExist,
            ValueError,
            TypeError,
            KeyError,
        ):
            return Response({"detail": ENLACE_INVALIDO}, status=400)
        usuario.email_verificado_en = timezone.now()
        usuario.save(update_fields=["email_verificado_en"])
        aprobada = SolicitudAcceso.objects.filter(
            usuario=usuario, estado="APROBADA"
        ).exists()
        autorizado = (
            UsuarioAutorizado.objects.filter(email=usuario.email, activo=True).first()
            if settings.PREAPROBACION_LISTA_BLANCA
            else None
        )
        if aprobada:
            usuario.cambiar_estado(EstadoCuenta.ACTIVA)
            sincronizar_autorizado(usuario)
        elif autorizado:
            aprobar_cuenta(
                usuario,
                {
                    "rol": autorizado.rol,
                    "carrera": autorizado.carrera,
                    "area": autorizado.area,
                    "sede": autorizado.sede,
                },
            )
        else:
            usuario.cambiar_estado(EstadoCuenta.PENDIENTE_APROBACION)
            solicitud, _ = SolicitudAcceso.objects.get_or_create(
                usuario=usuario,
                defaults={
                    "rol_solicitado": usuario.rol,
                    "carrera": usuario.carrera,
                    "sede": usuario.sede,
                },
            )
            avisar_solicitud(solicitud)
        return Response({"estado": usuario.estado_cuenta})


class ReenviarVerificacion(Publica):
    @transaction.atomic
    def post(self, request):
        serial = CorreoSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        usuario = (
            Usuario.objects.select_for_update()
            .filter(
                email=serial.validated_data["email"],
                estado_cuenta=EstadoCuenta.PENDIENTE_VERIFICACION,
            )
            .first()
        )
        if usuario:
            enviar_verificacion(usuario)
        return Response({"detail": GENERICO_CORREO})


class Login(Publica):
    throttle_scope = "login"

    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        password = request.data.get("password", "")
        if not isinstance(password, str):
            raise ValidationError({"password": "La contraseña debe ser texto"})
        if len(email) > 254:
            raise ValidationError({"email": "Correo inválido"})
        desde = timezone.now() - timedelta(minutes=15)
        if (
            IntentoLogin.objects.filter(
                email=email, exitoso=False, creado__gte=desde
            ).count()
            >= 5
        ):
            IntentoLogin.objects.create(
                email=email, ip=ip_cliente(request), exitoso=False
            )
            return Response(
                {
                    "detail": "Demasiados intentos. Espera 15 minutos o recupera tu contraseña."
                },
                status=429,
            )
        usuario = Usuario.objects.filter(email=email).first()
        correcta = check_password(
            password,
            (
                usuario.password
                if usuario and usuario.has_usable_password()
                else HASH_FICTICIO
            ),
        )
        IntentoLogin.objects.create(
            email=email,
            ip=ip_cliente(request),
            exitoso=correcta and puede_iniciar_sesion(usuario),
        )
        if not usuario or not correcta:
            return Response({"detail": "Correo o contraseña incorrectos"}, status=401)
        codigos = {
            EstadoCuenta.PENDIENTE_VERIFICACION: "correo_no_verificado",
            EstadoCuenta.PENDIENTE_APROBACION: "pendiente_aprobacion",
            EstadoCuenta.RECHAZADA: "rechazada",
            EstadoCuenta.DESACTIVADA: "desactivada",
        }
        if not puede_iniciar_sesion(usuario):
            datos = {
                "codigo": codigos.get(
                    usuario.estado_cuenta,
                    (
                        "correo_no_verificado"
                        if not usuario.email_verificado_en
                        else "desactivada"
                    ),
                ),
                "detail": usuario.get_estado_cuenta_display(),
            }
            if usuario.estado_cuenta == EstadoCuenta.RECHAZADA:
                datos["motivo"] = getattr(
                    getattr(usuario, "solicitud", None), "motivo_rechazo", ""
                )
            return Response(datos, status=403)
        update_last_login(None, usuario)
        token = RefreshToken.for_user(usuario)
        return poner_refresh(
            Response(
                {
                    "access": str(token.access_token),
                    "usuario": UsuarioSerializer(usuario).data,
                }
            ),
            token,
        )


class Recuperar(Publica):
    @transaction.atomic
    def post(self, request):
        serial = CorreoSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        usuario = (
            Usuario.objects.select_for_update()
            .filter(
                email=serial.validated_data["email"],
                estado_cuenta=EstadoCuenta.ACTIVA,
                is_active=True,
            )
            .first()
        )
        if usuario:
            ahora = timezone.now()
            if (
                not usuario.inicio_recuperaciones
                or usuario.inicio_recuperaciones <= ahora - timedelta(hours=1)
            ):
                usuario.inicio_recuperaciones = ahora
                usuario.contador_recuperaciones = 0
            if usuario.contador_recuperaciones < 3:
                usuario.contador_recuperaciones += 1
                usuario.save(
                    update_fields=["inicio_recuperaciones", "contador_recuperaciones"]
                )
                uid = urlsafe_base64_encode(force_bytes(usuario.pk))
                token = default_token_generator.make_token(usuario)
                enlace = settings.FRONTEND_URL + f"/restablecer?uid={uid}&token={token}"
                transaction.on_commit(
                    lambda: enviar_correo("recuperacion", usuario, enlace), robust=True
                )
        return Response({"detail": GENERICO_CORREO})


def validar_nueva_password(datos, usuario, campo="password", confirmacion="password2"):
    password = datos.get(campo, "")
    if not isinstance(password, str) or password != datos.get(confirmacion):
        raise ValidationError({confirmacion: "Las contraseñas no coinciden"})
    try:
        validate_password(password, usuario)
    except ErrorDjango as exc:
        raise ValidationError({campo: exc.messages})
    return password


class Restablecer(Publica):
    @transaction.atomic
    def post(self, request):
        try:
            usuario = Usuario.objects.select_for_update().get(
                pk=force_str(urlsafe_base64_decode(request.data.get("uid", ""))),
                estado_cuenta=EstadoCuenta.ACTIVA,
            )
        except (
            Usuario.DoesNotExist,
            ValueError,
            TypeError,
            OverflowError,
            UnicodeDecodeError,
        ):
            return Response({"detail": ENLACE_INVALIDO}, status=400)
        if not isinstance(request.data.get("token"), str):
            return Response({"detail": ENLACE_INVALIDO}, status=400)
        if not default_token_generator.check_token(
            usuario, request.data.get("token", "")
        ):
            return Response({"detail": ENLACE_INVALIDO}, status=400)
        password = validar_nueva_password(request.data, usuario)
        usuario.set_password(password)
        usuario.save(update_fields=["password"])
        revocar_sesiones(usuario)
        IntentoLogin.objects.filter(email=usuario.email, exitoso=False).delete()
        return Response({"detail": "Contraseña restablecida. Ya puedes ingresar."})


class CambiarPassword(APIView):
    @transaction.atomic
    def post(self, request):
        usuario = Usuario.objects.select_for_update().get(pk=request.user.pk)
        if not puede_iniciar_sesion(usuario):
            return Response(
                {"detail": "La cuenta no tiene una sesión habilitada"}, status=403
            )
        if not isinstance(
            request.data.get("actual"), str
        ) or not usuario.check_password(request.data.get("actual", "")):
            raise ValidationError({"actual": "Contraseña actual incorrecta"})
        password = validar_nueva_password(request.data, usuario, "nueva", "nueva2")
        usuario.set_password(password)
        usuario.save(update_fields=["password"])
        revocar_sesiones(usuario)
        token = RefreshToken.for_user(usuario)
        return poner_refresh(Response({"access": str(token.access_token)}), token)
