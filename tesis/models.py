from django.db import models
from django.conf import settings
from .almacenamiento import privado, ruta_privada


class Estado(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    EN_REVISION = "EN_REVISION", "En revisión"
    PUBLICADA = "PUBLICADA", "Publicada"
    RECHAZADA = "RECHAZADA", "Rechazada"


class TipoTrabajo(models.TextChoices):
    PROYECTO_TITULO = "PROYECTO_TITULO", "Proyecto de título"
    PROYECTO_INTEGRADO = "PROYECTO_INTEGRADO", "Proyecto integrado"


class Tesis(models.Model):
    autoriza_publicacion = models.BooleanField(default=False)
    autorizacion_version = models.CharField(max_length=50, blank=True)
    autorizacion_en = models.DateTimeField(null=True, blank=True)
    publicada_alguna_vez = models.BooleanField(default=False, editable=False)
    titulo = models.CharField(max_length=300)
    resumen = models.TextField()
    palabras_clave = models.CharField(max_length=500, blank=True)
    tipo = models.CharField(max_length=30, choices=TipoTrabajo.choices)
    anio = models.PositiveIntegerField()
    periodo = models.PositiveSmallIntegerField(
        choices=[(1, "1"), (2, "2")], null=True, blank=True
    )
    carrera = models.ForeignKey("academico.Carrera", on_delete=models.PROTECT)
    sede = models.ForeignKey("academico.Sede", on_delete=models.PROTECT)
    profesor_guia = models.CharField(max_length=200)
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.EN_REVISION
    )
    observacion_revision = models.TextField(blank=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tesis_subidas"
    )
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tesis_revisadas",
    )
    fecha_publicacion = models.DateTimeField(null=True, blank=True)
    pdf_original = models.FileField(storage=privado, upload_to=ruta_privada)
    pdf_marcado = models.FileField(storage=privado, upload_to=ruta_privada)
    hash_sha256 = models.CharField(max_length=64, unique=True)
    num_paginas = models.PositiveIntegerField(default=0)
    tamano_bytes = models.PositiveIntegerField(default=0)
    texto_extraido = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.estado == Estado.PUBLICADA or self.fecha_publicacion:
            self.publicada_alguna_vez = True
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                    "publicada_alguna_vez"
                }
        super().save(*args, **kwargs)

    def __str__(self):
        return self.titulo


class AutorTesis(models.Model):
    tesis = models.ForeignKey(Tesis, on_delete=models.CASCADE, related_name="autores")
    nombre_completo = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]


class MaterialAdicional(models.Model):
    tesis = models.ForeignKey(
        Tesis, on_delete=models.CASCADE, related_name="materiales"
    )
    tipo = models.CharField(
        max_length=20, choices=[(x, x) for x in ["REPOSITORIO", "ARCHIVO", "ENLACE"]]
    )
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    url = models.URLField(blank=True)
    archivo = models.FileField(
        storage=privado, upload_to=ruta_privada, null=True, blank=True
    )
    solo_carrera = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)


class RegistroAcceso(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    tesis = models.ForeignKey(Tesis, on_delete=models.SET_NULL, null=True)
    accion = models.CharField(
        max_length=30,
        choices=[(x, x) for x in ["VER_PDF", "VER_REPOSITORIO", "DESCARGAR_MATERIAL"]],
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from privacidad.utils import truncar_ip

        self.ip = truncar_ip(self.ip) or None
        super().save(*args, **kwargs)
