from django.contrib import admin
from django.urls import path, include
from .views import Salud
from rest_framework.routers import DefaultRouter
from usuarios.views import (
    MiUsuario,
    RenovarSesion,
    CerrarSesion,
    AutorizadosViewSet,
)
from usuarios.auth_views import (
    Registro,
    VerificarCorreo,
    ReenviarVerificacion,
    Login,
    Recuperar,
    Restablecer,
    CambiarPassword,
)
from usuarios.solicitudes import SolicitudesViewSet
from tesis.views import TesisViewSet, MaterialViewSet
from notificaciones.views import NotificacionesViewSet
from academico.views import (
    Sedes,
    Areas,
    Carreras,
    Anios,
    Profesores,
    CatalogoTipos,
    SedesAdmin,
    Regiones,
    Niveles,
)

router = DefaultRouter()
router.register("solicitudes", SolicitudesViewSet, basename="solicitudes")
router.register("admin/sedes", SedesAdmin, basename="admin-sedes")
router.register("notificaciones", NotificacionesViewSet, basename="notificaciones")
router.register("tesis", TesisViewSet, basename="tesis")
router.register("materiales", MaterialViewSet, basename="materiales")
router.register("admin/autorizados", AutorizadosViewSet, basename="autorizados")
urlpatterns = [
    path("api/auth/registro/", Registro.as_view()),
    path("api/auth/verificar-correo/", VerificarCorreo.as_view()),
    path("api/auth/reenviar-verificacion/", ReenviarVerificacion.as_view()),
    path("api/auth/login/", Login.as_view()),
    path("api/auth/recuperar/", Recuperar.as_view()),
    path("api/auth/restablecer/", Restablecer.as_view()),
    path("api/auth/cambiar-password/", CambiarPassword.as_view()),
    path("api/catalogos/regiones/", Regiones.as_view()),
    path("api/catalogos/niveles/", Niveles.as_view()),
    path("api/salud/", Salud.as_view()),
    path("admin/", admin.site.urls),
    path("api/auth/refresh/", RenovarSesion.as_view()),
    path("api/auth/me/", MiUsuario.as_view()),
    path("api/auth/logout/", CerrarSesion.as_view()),
    path("api/catalogos/sedes/", Sedes.as_view()),
    path("api/catalogos/areas/", Areas.as_view()),
    path("api/catalogos/carreras/", Carreras.as_view()),
    path("api/catalogos/anios/", Anios.as_view()),
    path("api/catalogos/tipos/", CatalogoTipos.as_view()),
    path("api/catalogos/profesores-guia/", Profesores.as_view()),
    path("api/", include(router.urls)),
]
