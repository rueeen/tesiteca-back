from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from usuarios.models import (
    Usuario,
    UsuarioAutorizado,
    SolicitudAcceso,
    IntentoLogin,
    Rol,
    EstadoCuenta,
)
from usuarios.cuentas import revocar_sesiones
from tesis.models import Tesis, AutorTesis, RegistroAcceso, Estado
from notificaciones.models import Notificacion, TicketWS
from .models import EventoPrivacidad, AceptacionPolitica

# Códigos cerrados: nunca persistir texto libre con nombres, RUT o correos en auditoría.
MOTIVOS = ("solicitud_titular", "solicitud_administrativa", "retencion")


class UltimoAdministrador(ValueError):
    pass


def borrar_archivos(archivos):
    for almacenamiento, nombre in archivos:
        almacenamiento.delete(nombre)


@transaction.atomic
def anonimizar_usuario(usuario, motivo, ejecutado_por=None):
    if motivo not in MOTIVOS:
        raise ValueError("Usa un motivo de privacidad válido")
    # Orden fijo de bloqueo para impedir que dos ADMIN se eliminen mutuamente.
    administradores = list(
        Usuario.objects.select_for_update()
        .filter(rol=Rol.ADMIN, estado_cuenta=EstadoCuenta.ACTIVA, is_active=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    usuario = Usuario.objects.select_for_update().get(pk=usuario.pk)
    if usuario.estado_cuenta == EstadoCuenta.ELIMINADA:
        return False
    if usuario.pk in administradores and len(administradores) == 1:
        raise UltimoAdministrador("No se puede anonimizar al último ADMIN activo")
    original = usuario.email
    revocar_sesiones(usuario)
    TicketWS.objects.filter(usuario=usuario).delete()
    UsuarioAutorizado.objects.filter(email__iexact=original).delete()
    IntentoLogin.objects.filter(email__iexact=original).delete()
    Notificacion.objects.filter(usuario=usuario).delete()
    SolicitudAcceso.objects.filter(usuario=usuario).update(
        mensaje="",
        motivo_rechazo="",
        rol_solicitado="",
        carrera=None,
        sede=None,
        revisada_por=None,
    )
    RegistroAcceso.objects.filter(usuario=usuario).update(usuario=None)
    AutorTesis.objects.filter(Q(usuario=usuario) | Q(email__iexact=original)).update(
        usuario=None, email=""
    )
    # El nombre de autor es parte del registro académico y se conserva.
    pendientes = Tesis.objects.select_for_update().filter(
        subido_por=usuario,
        publicada_alguna_vez=False,
        fecha_publicacion__isnull=True,
        estado__in=[Estado.BORRADOR, Estado.EN_REVISION, Estado.RECHAZADA],
    )
    archivos = []
    for tesis in pendientes.prefetch_related("materiales"):
        for archivo in [
            tesis.pdf_original,
            tesis.pdf_marcado,
            *(m.archivo for m in tesis.materiales.all()),
        ]:
            if archivo and archivo.name:
                archivos.append((archivo.storage, archivo.name))
    pendientes.delete()
    # El almacenamiento no participa en la transacción SQL: borrar solo tras commit.
    transaction.on_commit(lambda: borrar_archivos(archivos))
    AceptacionPolitica.objects.filter(usuario=usuario).delete()
    usuario.email = f"anonimo-{usuario.pk}@anonimo.invalid"
    usuario.nombre_completo = "Usuario eliminado"
    usuario.rut = usuario.first_name = usuario.last_name = ""
    usuario.set_unusable_password()
    usuario.estado_cuenta = EstadoCuenta.ELIMINADA
    usuario.is_staff = usuario.is_superuser = False
    usuario.carrera = usuario.area = usuario.sede = None
    for campo in [
        "email_verificado_en",
        "politica_aceptada_version",
        "politica_aceptada_en",
        "last_login",
        "ultimo_envio_verificacion",
        "inicio_envios_verificacion",
        "inicio_recuperaciones",
    ]:
        setattr(usuario, campo, None)
    usuario.contador_envios_verificacion = usuario.contador_recuperaciones = 0
    usuario.save()
    usuario.groups.clear()
    usuario.user_permissions.clear()
    EventoPrivacidad.objects.create(
        tipo="anonimizacion",
        usuario_id_original=usuario.pk,
        motivo=motivo,
        ejecutado_por=ejecutado_por,
    )
    return True


def lecturas_antiguas(dias):
    if dias <= 0:
        return RegistroAcceso.objects.none()
    return RegistroAcceso.objects.filter(
        fecha__lt=timezone.now() - timedelta(days=dias)
    ).filter(Q(usuario__isnull=False) | ~Q(user_agent=""))


def rechazadas_antiguas(dias):
    if dias <= 0:
        return Usuario.objects.none()
    return Usuario.objects.filter(
        estado_cuenta=EstadoCuenta.RECHAZADA,
        solicitud__estado="RECHAZADA",
        solicitud__revisada_en__lt=timezone.now() - timedelta(days=dias),
    )


def cuentas_inactivas(dias):
    if dias <= 0:
        return Usuario.objects.none()
    return Usuario.objects.filter(
        estado_cuenta=EstadoCuenta.ACTIVA,
        last_login__lt=timezone.now() - timedelta(days=dias),
    ).exclude(rol=Rol.ADMIN)


def anonimizar_lecturas_antiguas(dias):
    return lecturas_antiguas(dias).update(usuario=None, user_agent="")


def limpiar_solicitudes_rechazadas(dias):
    return sum(
        anonimizar_usuario(u, "retencion") for u in rechazadas_antiguas(dias).iterator()
    )


def limpiar_cuentas_inactivas(dias):
    return sum(
        anonimizar_usuario(u, "retencion") for u in cuentas_inactivas(dias).iterator()
    )
