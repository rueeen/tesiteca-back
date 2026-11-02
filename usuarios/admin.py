from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .forms import CrearUsuarioForm, EditarUsuarioForm
from .models import Usuario, UsuarioAutorizado, ImportacionLote, CodigoAcceso


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    add_form = CrearUsuarioForm
    form = EditarUsuarioForm
    ordering = ["email"]
    list_display = ["email", "nombre_completo", "rol", "carrera", "is_active"]
    list_filter = ["rol", "carrera", "is_active"]
    search_fields = ["email", "nombre_completo", "rut"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Datos",
            {"fields": ("rut", "nombre_completo", "rol", "carrera", "area", "sede")},
        ),
        (
            "Permisos",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {"fields": ("email", "nombre_completo", "password1", "password2", "rol")},
        ),
    )


@admin.register(UsuarioAutorizado)
class AutorizadoAdmin(admin.ModelAdmin):
    list_display = ["email", "nombre_completo", "rol", "carrera", "activo"]
    list_filter = ["rol", "carrera", "activo"]
    search_fields = ["email", "nombre_completo", "rut"]


@admin.register(ImportacionLote)
class LoteAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "creado_por",
        "fecha",
        "total_filas",
        "creados",
        "actualizados",
    ]
    list_filter = ["fecha"]
    search_fields = ["creado_por__email"]
    exclude = ["archivo"]


@admin.register(CodigoAcceso)
class CodigoAdmin(admin.ModelAdmin):
    list_display = ["email", "expira_en", "intentos", "usado"]
    list_filter = ["usado"]
    search_fields = ["email"]
    exclude = ["codigo_hash"]

    def has_add_permission(self, request):
        return False
