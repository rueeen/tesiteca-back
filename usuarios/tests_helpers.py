"""Cuentas ya aprobadas y verificadas para fixtures; no omite la regla en producción."""

from django.utils import timezone
from .models import Usuario, EstadoCuenta, SolicitudAcceso


def crear_usuario_activo(email, password=None, **datos):
    usuario = Usuario.objects.create_user(email, password, **datos)
    usuario.email_verificado_en = timezone.now()
    usuario.save(update_fields=["email_verificado_en"])
    SolicitudAcceso.objects.create(
        usuario=usuario,
        rol_solicitado=usuario.rol,
        carrera=usuario.carrera,
        sede=usuario.sede,
        estado="APROBADA",
        mensaje="Fixture verificada",
    )
    usuario.cambiar_estado(EstadoCuenta.ACTIVA)
    return usuario
