import hashlib
import logging
from datetime import timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
    BlacklistedToken,
)
from notificaciones.servicios import notificar
from .models import Usuario, UsuarioAutorizado, SolicitudAcceso, Rol, EstadoCuenta

SAL_VERIFICACION = "usuarios.verificacion.v1"
logger = logging.getLogger(__name__)


def revocar_sesiones(usuario):
    for token in OutstandingToken.objects.filter(user=usuario):
        BlacklistedToken.objects.get_or_create(token=token)


def sello_verificacion(usuario):
    return hashlib.sha256(
        f"{usuario.email}:{usuario.email_verificado_en}".encode()
    ).hexdigest()


def token_verificacion(usuario):
    return signing.dumps(
        {"id": usuario.pk, "sello": sello_verificacion(usuario)}, salt=SAL_VERIFICACION
    )


def enviar_correo(tipo, usuario, enlace):
    try:
        contexto = {"usuario": usuario, "enlace": enlace}
        asunto = (
            "[Tesiteca] Valida tu cuenta"
            if tipo == "verificacion"
            else "[Tesiteca] Recupera tu contraseña"
        )
        correo = EmailMultiAlternatives(
            asunto,
            render_to_string(f"correos/{tipo}.txt", contexto),
            settings.DEFAULT_FROM_EMAIL,
            [usuario.email],
        )
        correo.attach_alternative(
            render_to_string(f"correos/{tipo}.html", contexto), "text/html"
        )
        correo.send()
    except Exception:
        logger.error("No se pudo entregar un correo de cuenta")


def enviar_verificacion(usuario):
    ahora = timezone.now()
    if (
        usuario.inicio_envios_verificacion is None
        or usuario.inicio_envios_verificacion <= ahora - timedelta(days=1)
    ):
        usuario.inicio_envios_verificacion = ahora
        usuario.contador_envios_verificacion = 0
    if usuario.contador_envios_verificacion >= 3:
        return
    usuario.contador_envios_verificacion += 1
    usuario.ultimo_envio_verificacion = ahora
    usuario.save(
        update_fields=[
            "inicio_envios_verificacion",
            "contador_envios_verificacion",
            "ultimo_envio_verificacion",
        ]
    )
    enlace = (
        settings.FRONTEND_URL
        + "/verificar-correo?"
        + urlencode({"token": token_verificacion(usuario)})
    )
    transaction.on_commit(
        lambda: enviar_correo("verificacion", usuario, enlace), robust=True
    )


def avisar_solicitud(solicitud):
    aprobadores = Usuario.objects.filter(is_active=True).filter(
        Q(rol=Rol.ADMIN)
        | (
            Q(sede=solicitud.sede)
            & (
                Q(rol=Rol.COORDINADOR, carrera=solicitud.carrera)
                | Q(
                    rol=Rol.DIRECTOR,
                    area_id=solicitud.carrera.area_id if solicitud.carrera else None,
                )
            )
        )
    )
    if solicitud.rol_solicitado == Rol.DIRECTOR:
        aprobadores = aprobadores.filter(rol=Rol.ADMIN)
    elif solicitud.rol_solicitado == Rol.COORDINADOR:
        aprobadores = aprobadores.exclude(rol=Rol.COORDINADOR)
    notificar(
        aprobadores,
        "SOLICITUD_ACCESO",
        "Nueva solicitud de acceso",
        f"{solicitud.usuario.nombre_completo} solicita acceso.",
        "/solicitudes",
        {"solicitud_id": solicitud.pk},
        actor=solicitud.usuario,
    )


def aprobar_cuenta(usuario, datos, revisor=None):
    from academico.models import Area

    carrera = datos.get("carrera")
    area = datos.get("area") or (carrera.area if carrera else None)
    if datos["rol"] == Rol.DIRECTOR and area is None:
        areas = list(Area.objects.filter(activa=True)[:2])
        if len(areas) == 1:
            area = areas[0]
    for campo in ["rol", "carrera", "sede"]:
        setattr(usuario, campo, datos.get(campo))
    usuario.area = area
    usuario.save(update_fields=["rol", "carrera", "area", "sede"])
    usuario.cambiar_estado(EstadoCuenta.ACTIVA)
    SolicitudAcceso.objects.filter(usuario=usuario).update(
        estado="APROBADA",
        motivo_rechazo="",
        rol_solicitado=usuario.rol,
        carrera=usuario.carrera,
        sede=usuario.sede,
        revisada_por=revisor,
        revisada_en=timezone.now(),
    )
    return usuario
