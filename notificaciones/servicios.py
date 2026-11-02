import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from usuarios.models import Usuario, Rol
from .models import Notificacion, TipoNotificacion
from .serializers import NotificacionSerializer

logger = logging.getLogger(__name__)


def notificar(usuarios, tipo, titulo, mensaje, enlace, datos=None, actor=None):
    ids = {
        usuario.pk
        for usuario in usuarios
        if usuario.pk and usuario.pk != getattr(actor, "pk", None)
    }
    destinatarios = list(Usuario.objects.filter(pk__in=ids, is_active=True))
    with transaction.atomic():
        notificaciones = Notificacion.objects.bulk_create(
            [
                Notificacion(
                    usuario=usuario,
                    tipo=tipo,
                    titulo=titulo[:120],
                    mensaje=mensaje[:500],
                    enlace=enlace,
                    datos=datos or {},
                )
                for usuario in destinatarios
            ]
        )

        def entregar():
            for notificacion in notificaciones:
                if settings.NOTIFICACIONES_WS:
                    try:
                        async_to_sync(get_channel_layer().group_send)(
                            f"usuario_{notificacion.usuario_id}",
                            {
                                "type": "notificacion.nueva",
                                "notificacion": dict(
                                    NotificacionSerializer(notificacion).data
                                ),
                            },
                        )
                    except Exception:
                        logger.exception(
                            "No se pudo entregar una notificación por WebSocket"
                        )
                if settings.NOTIFICAR_POR_CORREO and tipo in (
                    TipoNotificacion.TESIS_APROBADA,
                    TipoNotificacion.TESIS_RECHAZADA,
                ):
                    try:
                        send_mail(
                            notificacion.titulo,
                            f"{notificacion.mensaje}\n{settings.FRONTEND_URL}{enlace}",
                            settings.DEFAULT_FROM_EMAIL,
                            [notificacion.usuario.email],
                        )
                    except Exception:
                        logger.error("No se pudo entregar una notificación por correo")

        transaction.on_commit(entregar, robust=True)
    return notificaciones


def avisar_revisores(tesis, actor, reenviada=False):
    revisores = Usuario.objects.filter(
        Q(rol=Rol.COORDINADOR, carrera_id=tesis.carrera_id)
        | Q(rol=Rol.DIRECTOR, area_id=tesis.carrera.area_id)
    )
    return notificar(
        revisores,
        (
            TipoNotificacion.TESIS_REENVIADA
            if reenviada
            else TipoNotificacion.TESIS_EN_REVISION
        ),
        "Tesis reenviada" if reenviada else "Nueva tesis en revisión",
        f"La tesis «{tesis.titulo}» está pendiente de revisión.",
        "/revision",
        {"tesis_id": tesis.pk},
        actor=actor,
    )


def avisar_autores(tesis, actor, aprobada):
    autores = Usuario.objects.filter(
        Q(pk=tesis.subido_por_id)
        | Q(
            pk__in=tesis.autores.exclude(usuario=None).values_list(
                "usuario_id", flat=True
            )
        )
    )
    mensaje = (
        f"Tu tesis «{tesis.titulo}» fue aprobada."
        if aprobada
        else f"Tu tesis «{tesis.titulo}» fue rechazada. {tesis.observacion_revision[:200]}"
    )
    return notificar(
        autores,
        (
            TipoNotificacion.TESIS_APROBADA
            if aprobada
            else TipoNotificacion.TESIS_RECHAZADA
        ),
        "Tesis aprobada" if aprobada else "Tesis rechazada",
        mensaje,
        f"/tesis/{tesis.pk}",
        {"tesis_id": tesis.pk},
        actor=actor,
    )
