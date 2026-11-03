from django.db.models import Q
from django.conf import settings
from rest_framework.permissions import BasePermission
from usuarios.models import Rol
from .models import Estado


def visibles(qs, usuario):
    if usuario.rol == Rol.ADMIN:
        return qs
    propias = Q(subido_por=usuario) | Q(autores__usuario=usuario)
    if usuario.rol == Rol.DIRECTOR and usuario.area_id:
        return qs.filter(
            Q(carrera__area_id=usuario.area_id, sede_id=usuario.sede_id)
        ).distinct()
    if usuario.rol == Rol.COORDINADOR and usuario.carrera_id:
        return qs.filter(
            Q(carrera_id=usuario.carrera_id, sede_id=usuario.sede_id)
        ).distinct()
    if usuario.rol == Rol.ESTUDIANTE and usuario.carrera_id:
        publicadas = Q(carrera_id=usuario.carrera_id, estado=Estado.PUBLICADA)
        if not settings.VISIBILIDAD_ENTRE_SEDES:
            publicadas &= Q(sede_id=usuario.sede_id)
        return qs.filter(publicadas | propias).distinct()
    return qs.filter(propias).distinct()


def revisa(usuario, tesis):
    return (
        usuario.rol == Rol.ADMIN
        or (
            usuario.rol == Rol.COORDINADOR
            and usuario.carrera_id == tesis.carrera_id
            and usuario.sede_id == tesis.sede_id
        )
        or (
            usuario.rol == Rol.DIRECTOR
            and usuario.area_id == tesis.carrera.area_id
            and usuario.sede_id == tesis.sede_id
        )
    )


def es_autor(usuario, tesis):
    return tesis.subido_por_id == usuario.id or any(
        autor.usuario_id == usuario.id for autor in tesis.autores.all()
    )


def puede_reenviar(usuario, tesis):
    return tesis.estado in (Estado.BORRADOR, Estado.RECHAZADA) and es_autor(
        usuario, tesis
    )


def edita(usuario, tesis):
    if revisa(usuario, tesis):
        return True
    return puede_reenviar(usuario, tesis)


def material_visible(usuario, material):
    return (
        not material.solo_carrera
        or usuario.rol == Rol.ADMIN
        or usuario.carrera_id == material.tesis.carrera_id
        or (
            usuario.rol == Rol.DIRECTOR
            and usuario.area_id == material.tesis.carrera.area_id
            and usuario.sede_id == material.tesis.sede_id
        )
    )


class PermisoTesis(BasePermission):
    def has_object_permission(self, request, view, obj):
        if view.action in [
            "partial_update",
            "update",
            "destroy",
            "materiales",
        ] and request.method not in ["GET", "HEAD", "OPTIONS"]:
            return edita(request.user, obj)
        return True
