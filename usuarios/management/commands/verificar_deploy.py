import tempfile
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BACKEND = "rvavalencia.pythonanywhere.com"
FRONTEND = "https://tesiteca-inacap.netlify.app"


class Command(BaseCommand):
    help = (
        "Verifica la configuración antes de recargar la web app gratuita de rvavalencia"
    )

    def handle(self, *args, **opciones):
        errores = []

        def comprobar(nombre, cumple, critico=True):
            self.stdout.write(f'{"✔" if cumple else "✘"} {nombre}')
            if not cumple and critico:
                errores.append(nombre)

        comprobar("DEBUG=False", not settings.DEBUG)
        clave = settings.SECRET_KEY
        comprobar(
            "SECRET_KEY de al menos 50 caracteres, distinta de los ejemplos",
            len(clave) >= 50
            and not clave.startswith("django-insecure-")
            and clave.lower()
            not in {"example" * 10, "changeme" * 10, "your-secret-key" * 5},
        )
        comprobar(
            f"ALLOWED_HOSTS contiene {BACKEND}", BACKEND in settings.ALLOWED_HOSTS
        )
        comprobar(
            "CSRF_TRUSTED_ORIGINS incluye Netlify y PythonAnywhere",
            {FRONTEND, f"https://{BACKEND}"}.issubset(settings.CSRF_TRUSTED_ORIGINS),
        )
        comprobar("SECURE_COOKIES=True", settings.SECURE_COOKIES)
        comprobar(
            "SMTP Gmail con usuario y contraseña configurados",
            settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
            and settings.EMAIL_HOST == "smtp.gmail.com"
            and bool(settings.EMAIL_HOST_USER)
            and bool(settings.EMAIL_HOST_PASSWORD),
        )
        comprobar(
            f"NETLIFY_PROXY_SECRET definido (largo: {len(settings.NETLIFY_PROXY_SECRET)})",
            bool(settings.NETLIFY_PROXY_SECRET),
        )
        comprobar(
            "NETLIFY_SITE_URL coincide con el sitio oficial",
            settings.NETLIFY_SITE_URL == FRONTEND,
        )
        comprobar("EXIGIR_PROXY_NETLIFY=True", settings.EXIGIR_PROXY_NETLIFY)
        comprobar(
            "NOTIFICACIONES_WS=False; en cuenta gratuita no hay ASGI (aviso)",
            not settings.NOTIFICACIONES_WS,
            critico=False,
        )
        privado = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        estatico = Path(settings.STATIC_ROOT).resolve()
        escribible = False
        if privado.is_dir():
            try:
                with tempfile.TemporaryFile(dir=privado):
                    escribible = True
            except OSError:
                pass
        comprobar(
            "PRIVATE_MEDIA_ROOT existe, permite escritura y está fuera de STATIC_ROOT",
            escribible and not privado.is_relative_to(estatico),
        )
        try:
            ejecutor = MigrationExecutor(connection)
            migrada = not ejecutor.migration_plan(ejecutor.loader.graph.leaf_nodes())
        except Exception:
            migrada = False
        comprobar("Base de datos sin migraciones pendientes", migrada)
        comprobar(
            "collectstatic ejecutado: STATIC_ROOT/admin existe",
            (estatico / "admin").is_dir(),
        )
        if errores:
            raise CommandError(f"Hay {len(errores)} comprobaciones críticas pendientes")
        self.stdout.write(
            self.style.SUCCESS("Configuración lista para recargar la web app")
        )
