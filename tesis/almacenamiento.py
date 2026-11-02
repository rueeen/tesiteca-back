from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class AlmacenamientoPrivado(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.PRIVATE_MEDIA_ROOT)

    def url(self, name):
        raise ValueError("El almacenamiento privado no expone URLs")


privado = AlmacenamientoPrivado()


def ruta_privada(instancia, nombre):
    tesis = getattr(instancia, "tesis", instancia)
    return f"{tesis.carrera.codigo}/{tesis.anio}/{uuid4().hex}{Path(nombre).suffix.lower()}"
