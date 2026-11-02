import hashlib
from io import BytesIO
from pypdf import PdfReader
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from usuarios.models import Rol
from .models import Tesis, AutorTesis, MaterialAdicional, Estado
from .marca_agua import generar_marca_fija


def validar_pdf(archivo, instancia=None):
    if archivo.size > settings.MAX_PDF_MB * 1024 * 1024:
        raise ValidationError("El PDF supera el tamaño máximo")
    datos = archivo.read()
    archivo.seek(0)
    if not datos.startswith(b"%PDF"):
        raise ValidationError("El archivo no es un PDF válido")
    huella = hashlib.sha256(datos).hexdigest()
    repetidas = Tesis.objects.filter(hash_sha256=huella)
    if instancia:
        repetidas = repetidas.exclude(pk=instancia.pk)
    if repetidas.exists():
        raise ValidationError("Este PDF ya fue subido")
    try:
        lector = PdfReader(BytesIO(datos))
        if lector.is_encrypted:
            raise ValueError("No se permiten PDFs encriptados")
        if not lector.pages:
            raise ValueError("El PDF no tiene páginas")
        texto = "\n".join(p.extract_text() or "" for p in lector.pages)
        return datos, dict(
            hash_sha256=huella,
            num_paginas=len(lector.pages),
            tamano_bytes=len(datos),
            texto_extraido=texto,
        )
    except Exception as exc:
        raise ValidationError(f"PDF inválido: {exc}")


def guardar_tesis(datos, usuario, instancia=None):
    datos = dict(datos)
    archivo = datos.pop("pdf", None)
    autores = datos.pop("autores", None)
    repositorio = datos.pop("repositorio_url", None)
    publicar = datos.pop("publicar", False)
    contenido, metadatos = validar_pdf(archivo, instancia) if archivo else (None, {})
    tesis = instancia or Tesis(subido_por=usuario)
    anteriores = [f.name for f in [tesis.pdf_original, tesis.pdf_marcado] if f.name]
    nuevos = []
    try:
        with transaction.atomic():
            for clave, valor in {**datos, **metadatos}.items():
                setattr(tesis, clave, valor)
            if not instancia:
                tesis.estado = (
                    Estado.PUBLICADA
                    if publicar and usuario.rol != Rol.ESTUDIANTE
                    else Estado.EN_REVISION
                )
                if tesis.estado == Estado.PUBLICADA:
                    tesis.fecha_publicacion = timezone.now()
                    tesis.revisado_por = usuario
            if contenido is not None:
                tesis.pdf_original.save(
                    "original.pdf", ContentFile(contenido), save=False
                )
                nuevos.append(tesis.pdf_original.name)
            tesis.save()
            if contenido is not None or (
                instancia and any(k in datos for k in ["carrera", "anio"])
            ):
                try:
                    generar_marca_fija(tesis)
                finally:
                    if tesis.pdf_marcado.name not in anteriores:
                        nuevos.append(tesis.pdf_marcado.name)
            if autores is not None:
                tesis.autores.all().delete()
                if usuario.rol == Rol.ESTUDIANTE and not any(
                    a.get("email", "").lower() == usuario.email for a in autores
                ):
                    autores.append(
                        {
                            "nombre_completo": usuario.nombre_completo,
                            "email": usuario.email,
                        }
                    )
                for orden, autor in enumerate(autores):
                    email = autor.get("email", "").lower()
                    AutorTesis.objects.create(
                        tesis=tesis,
                        orden=orden,
                        usuario=usuario if email == usuario.email else None,
                        **{**autor, "email": email},
                    )
            if repositorio:
                MaterialAdicional.objects.create(
                    tesis=tesis,
                    tipo="REPOSITORIO",
                    titulo="Repositorio",
                    url=repositorio,
                    solo_carrera=True,
                )
            if nuevos:
                mantener = {tesis.pdf_original.name, tesis.pdf_marcado.name}
                transaction.on_commit(
                    lambda: [
                        tesis.pdf_original.storage.delete(n)
                        for n in anteriores
                        if n not in mantener
                    ],
                    robust=True,
                )
        tesis._prefetched_objects_cache = {}
        return tesis
    except Exception as exc:
        for nombre in nuevos:
            if nombre and nombre not in anteriores:
                tesis.pdf_original.storage.delete(nombre)
        if (
            isinstance(exc, IntegrityError)
            and Tesis.objects.filter(
                hash_sha256=metadatos.get("hash_sha256", "")
            ).exists()
        ):
            raise ValidationError("Este PDF ya fue subido") from exc
        raise
