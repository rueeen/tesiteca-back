from rest_framework.permissions import BasePermission
from .models import Rol


def puede_administrar(usuario, datos):
    rol = datos.get("rol")
    carrera = datos.get("carrera")
    sede = datos.get("sede")
    if usuario.rol != Rol.ADMIN and (not sede or sede.pk != usuario.sede_id):
        return False
    if usuario.rol == Rol.ADMIN:
        return True
    if usuario.rol == Rol.COORDINADOR:
        return bool(
            usuario.carrera_id
            and rol == Rol.ESTUDIANTE
            and carrera
            and carrera.id == usuario.carrera_id
        )
    if usuario.rol == Rol.DIRECTOR:
        return bool(
            usuario.area_id
            and rol in (Rol.ESTUDIANTE, Rol.COORDINADOR)
            and carrera
            and carrera.area_id == usuario.area_id
        )
    return False


class GestionaAutorizados(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol in (
            Rol.ADMIN,
            Rol.COORDINADOR,
            Rol.DIRECTOR,
        )
