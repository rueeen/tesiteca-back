from django.conf import settings
from django.core.checks import Warning, register


@register()
def comprobar_produccion(app_configs, **kwargs):
    avisos = []
    if not settings.DEBUG:
        if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
            avisos.append(
                Warning(
                    "Los enlaces de verificación y recuperación no llegarán por correo",
                    id="usuarios.W001",
                )
            )
        if not settings.SECURE_COOKIES:
            avisos.append(
                Warning("SECURE_COOKIES=False en producción", id="usuarios.W002")
            )
    return avisos
