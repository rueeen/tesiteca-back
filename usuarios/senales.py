from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
    BlacklistedToken,
)
from .models import UsuarioAutorizado, Usuario


@receiver(post_save, sender=UsuarioAutorizado)
def sincronizar_activacion(sender, instance, **kwargs):
    usuario = Usuario.objects.filter(email=instance.email).first()
    if usuario is None:
        return
    Usuario.objects.filter(pk=usuario.pk).update(is_active=instance.activo)
    if not instance.activo:
        for token in OutstandingToken.objects.filter(user=usuario):
            BlacklistedToken.objects.get_or_create(token=token)
