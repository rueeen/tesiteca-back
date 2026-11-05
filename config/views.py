import subprocess
from functools import lru_cache
from django.conf import settings
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from config.throttling import ThrottleIP
from rest_framework.views import APIView


@lru_cache(maxsize=1)
def version_git():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=settings.BASE_DIR,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


class Salud(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ThrottleIP]
    throttle_scope = "salud"

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return Response(
            {
                "estado": "ok",
                "politica_privacidad_version": settings.POLITICA_PRIVACIDAD_VERSION,
                "version": version_git() or settings.APP_VERSION or "dev",
                "debug": settings.DEBUG,
                "via_proxy": getattr(request, "via_proxy", False),
                "notificaciones_ws": settings.NOTIFICACIONES_WS,
                "correo": (
                    "smtp"
                    if settings.EMAIL_BACKEND
                    == "django.core.mail.backends.smtp.EmailBackend"
                    else "consola"
                ),
                "base_datos": "ok",
            }
        )
