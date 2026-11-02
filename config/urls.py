from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from usuarios.views import (
    SolicitarCodigo,
    VerificarCodigo,
    MiUsuario,
    AutorizadosViewSet,
)
from tesis.views import TesisViewSet, MaterialViewSet
from academico.views import Sedes, Areas, Carreras, Anios, Profesores

router = DefaultRouter()
router.register("tesis", TesisViewSet, basename="tesis")
router.register("materiales", MaterialViewSet, basename="materiales")
router.register("admin/autorizados", AutorizadosViewSet, basename="autorizados")
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/solicitar-codigo/", SolicitarCodigo.as_view()),
    path("api/auth/verificar-codigo/", VerificarCodigo.as_view()),
    path("api/auth/refresh/", TokenRefreshView.as_view()),
    path("api/auth/me/", MiUsuario.as_view()),
    path("api/catalogos/sedes/", Sedes.as_view()),
    path("api/catalogos/areas/", Areas.as_view()),
    path("api/catalogos/carreras/", Carreras.as_view()),
    path("api/catalogos/anios/", Anios.as_view()),
    path("api/catalogos/profesores-guia/", Profesores.as_view()),
    path("api/", include(router.urls)),
]
