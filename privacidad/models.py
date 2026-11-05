from django.conf import settings
from django.db import models


class EventoPrivacidad(models.Model):
    tipo = models.CharField(
        max_length=40,
        choices=[("anonimizacion", "Anonimización"), ("ver_rut", "Consulta de RUT")],
    )
    fecha = models.DateTimeField(auto_now_add=True)
    usuario_id_original = models.PositiveBigIntegerField()
    motivo = models.CharField(max_length=40)
    ejecutado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )


class AceptacionPolitica(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="aceptaciones_politica",
    )
    version = models.CharField(max_length=50)
    fecha = models.DateTimeField(auto_now_add=True)
