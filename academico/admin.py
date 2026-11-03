from django.contrib import admin
from .models import Sede, Area, Carrera


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ["nombre", "ciudad", "region", "orden", "activa"]
    list_filter = ["activa"]
    search_fields = ["nombre", "ciudad"]


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "activa"]
    list_filter = ["activa"]
    search_fields = ["nombre"]


@admin.register(Carrera)
class CarreraAdmin(admin.ModelAdmin):
    list_display = [
        "codigo",
        "nombre",
        "area",
        "activa",
        "permite_repositorio",
        "nivel_formacion",
        "duracion_semestres",
    ]
    list_filter = [
        "area",
        "activa",
        "permite_repositorio",
        "nivel_formacion",
        "duracion_semestres",
    ]
    search_fields = ["nombre", "codigo"]
