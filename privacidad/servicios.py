from django.conf import settings
from django.db import transaction
from django.utils import timezone
from usuarios.models import Usuario
from .models import AceptacionPolitica


@transaction.atomic
def aceptar_politica(usuario):
    # Serializa aceptaciones y supresiones de una misma cuenta.
    actual = Usuario.objects.select_for_update().get(pk=usuario.pk)
    if actual.estado_cuenta == "ELIMINADA":
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("La cuenta está eliminada")
    actual.politica_aceptada_version = settings.POLITICA_PRIVACIDAD_VERSION
    actual.politica_aceptada_en = timezone.now()
    actual.save(update_fields=["politica_aceptada_version", "politica_aceptada_en"])
    AceptacionPolitica.objects.create(
        usuario=actual, version=actual.politica_aceptada_version
    )
    usuario.politica_aceptada_version = actual.politica_aceptada_version
    usuario.politica_aceptada_en = actual.politica_aceptada_en
