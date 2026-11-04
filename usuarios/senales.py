from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UsuarioAutorizado, Usuario, EstadoCuenta, SolicitudAcceso


@receiver(post_save, sender=UsuarioAutorizado)
def sincronizar_activacion(sender, instance, **kwargs):
    from .cuentas import aprobar_cuenta, revocar_sesiones

    usuario = Usuario.objects.filter(email=instance.email).first()
    if usuario is None:
        return
    aprobada = SolicitudAcceso.objects.filter(
        usuario=usuario, estado="APROBADA"
    ).exists()
    if not instance.activo:
        usuario.cambiar_estado(EstadoCuenta.DESACTIVADA)
        revocar_sesiones(usuario)
    elif (
        settings.PREAPROBACION_LISTA_BLANCA
        and not aprobada
        and usuario.estado_cuenta
        in (EstadoCuenta.PENDIENTE_VERIFICACION, EstadoCuenta.PENDIENTE_APROBACION)
    ):
        aprobar_cuenta(
            usuario,
            {
                "rol": instance.rol,
                "carrera": instance.carrera,
                "area": instance.area,
                "sede": instance.sede,
            },
            revisor=instance.lote.creado_por if instance.lote_id else None,
        )
    elif (
        usuario.estado_cuenta == EstadoCuenta.DESACTIVADA
        and usuario.email_verificado_en
        and aprobada
    ):
        usuario.cambiar_estado(EstadoCuenta.ACTIVA)

    elif usuario.estado_cuenta == EstadoCuenta.ACTIVA:
        rol_anterior = usuario.rol
        for campo in ["rol", "carrera", "area", "sede"]:
            setattr(usuario, campo, getattr(instance, campo))
        usuario.save(update_fields=["rol", "carrera", "area", "sede"])
        SolicitudAcceso.objects.filter(usuario=usuario, estado="APROBADA").update(
            rol_solicitado=usuario.rol, carrera=usuario.carrera, sede=usuario.sede
        )
        if rol_anterior != usuario.rol:
            revocar_sesiones(usuario)
