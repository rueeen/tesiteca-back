import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.core.asgi import get_asgi_application

# Inicializar Django antes de importar modelos usados en middleware y consumers.
django_asgi = get_asgi_application()
from django.conf import settings
from django.urls import path
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from notificaciones.middleware import TicketAuthMiddleware
from notificaciones.consumers import NotificacionesConsumer

application = ProtocolTypeRouter(
    {
        "http": django_asgi,
        "websocket": OriginValidator(
            TicketAuthMiddleware(
                URLRouter(
                    [path("ws/notificaciones/", NotificacionesConsumer.as_asgi())]
                )
            ),
            settings.WS_ALLOWED_ORIGINS,
        ),
    }
)
