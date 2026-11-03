from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import UsuarioAutorizado, Usuario, EstadoCuenta


@receiver(post_save, sender=UsuarioAutorizado)
def sincronizar_activacion(sender, instance, **kwargs):
    from .cuentas import aprobar_cuenta, revocar_sesiones

    usuario = Usuario.objects.filter(email=instance.email).first()
    if usuario is None:
        return
    if not instance.activo:
        usuario.cambiar_estado(EstadoCuenta.DESACTIVADA)
        revocar_sesiones(usuario)
    elif usuario.estado_cuenta == EstadoCuenta.PENDIENTE_APROBACION:
        aprobar_cuenta(
            usuario,
            {
                "rol": instance.rol,
                "carrera": instance.carrera,
                "area": instance.area,
                "sede": instance.sede,
            },
        )
    elif (
        usuario.estado_cuenta == EstadoCuenta.DESACTIVADA
        and usuario.email_verificado_en
    ):
        usuario.cambiar_estado(EstadoCuenta.ACTIVA)
