from django.conf import settings
from django.db import models


class TipoNotificacion(models.TextChoices):
    TESIS_EN_REVISION = "TESIS_EN_REVISION", "Tesis en revisión"
    TESIS_APROBADA = "TESIS_APROBADA", "Tesis aprobada"
    TESIS_RECHAZADA = "TESIS_RECHAZADA", "Tesis rechazada"
    TESIS_REENVIADA = "TESIS_REENVIADA", "Tesis reenviada"


class Notificacion(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )
    tipo = models.CharField(max_length=30, choices=TipoNotificacion.choices)
    titulo = models.CharField(max_length=120)
    mensaje = models.CharField(max_length=500)
    enlace = models.CharField(max_length=300)
    datos = models.JSONField(default=dict)
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada", "-id"]
        indexes = [models.Index(fields=["usuario", "leida", "-creada"])]


class TicketWS(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ticket_hash = models.CharField(max_length=64, unique=True)
    expira_en = models.DateTimeField()
    usado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
