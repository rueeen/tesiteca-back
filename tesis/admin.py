from django.contrib import admin
from django.utils import timezone
from .models import Tesis, AutorTesis, MaterialAdicional, RegistroAcceso, Estado
from .marca_agua import regenerar_marca


@admin.register(Tesis)
class TesisAdmin(admin.ModelAdmin):
    list_display = ["titulo", "carrera", "anio", "estado", "subido_por"]
    list_filter = ["carrera", "estado", "anio"]
    search_fields = ["titulo", "resumen", "autores__nombre_completo"]
    exclude = ["pdf_original", "pdf_marcado"]
    actions = ["aprobar", "regenerar"]

    @admin.action(description="Aprobar")
    def aprobar(self, request, queryset):
        queryset.filter(estado=Estado.EN_REVISION).update(
            estado=Estado.PUBLICADA,
            fecha_publicacion=timezone.now(),
            revisado_por=request.user,
            observacion_revision="",
        )

    @admin.action(description="Regenerar marca de agua")
    def regenerar(self, request, queryset):
        for tesis in queryset:
            try:
                regenerar_marca(tesis)
            except Exception:
                self.message_user(
                    request, f"No se pudo regenerar la tesis {tesis.pk}", level="ERROR"
                )


@admin.register(AutorTesis)
class AutorAdmin(admin.ModelAdmin):
    list_display = ["nombre_completo", "tesis", "orden"]
    list_filter = ["tesis__carrera"]
    search_fields = ["nombre_completo", "email"]


@admin.register(MaterialAdicional)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ["titulo", "tesis", "tipo", "solo_carrera"]
    list_filter = ["tipo", "solo_carrera"]
    search_fields = ["titulo", "tesis__titulo"]
    exclude = ["archivo"]


@admin.register(RegistroAcceso)
class RegistroAdmin(admin.ModelAdmin):
    list_display = ["usuario", "tesis", "accion", "ip", "fecha"]
    list_filter = ["accion", "fecha"]
    search_fields = ["usuario__email", "tesis__titulo", "ip"]
    readonly_fields = [f.name for f in RegistroAcceso._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
