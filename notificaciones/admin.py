from django.contrib import admin
from .models import Notificacion, TicketWS


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ["usuario", "tipo", "titulo", "leida", "creada"]
    list_filter = ["tipo", "leida", "creada"]
    search_fields = ["usuario__email", "titulo"]


@admin.register(TicketWS)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["usuario", "expira_en", "usado", "creado"]
    list_filter = ["usado"]
    search_fields = ["usuario__email"]
    exclude = ["ticket_hash"]

    def has_add_permission(self, request):
        return False
