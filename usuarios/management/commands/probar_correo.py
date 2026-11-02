from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envía un correo de prueba sin mostrar la contraseña SMTP"

    def add_arguments(self, parser):
        parser.add_argument("destino")

    def handle(self, *args, **opciones):
        try:
            validate_email(opciones["destino"])
        except ValidationError as exc:
            raise CommandError("Destino inválido") from exc
        self.stdout.write(
            f"Host: {settings.EMAIL_HOST} | Puerto: {settings.EMAIL_PORT} | Usuario: {settings.EMAIL_HOST_USER}"
        )
        try:
            enviados = send_mail(
                "Prueba de correo de Tesiteca",
                "El correo de Tesiteca está configurado correctamente.",
                settings.DEFAULT_FROM_EMAIL,
                [opciones["destino"]],
            )
            if enviados != 1:
                raise RuntimeError("El backend no confirmó el envío")
        except Exception as exc:
            # Conservar tipo y mensaje del transporte, pero nunca imprimir la contraseña.
            detalle = f"{type(exc).__name__}: {exc}"
            if settings.EMAIL_HOST_PASSWORD:
                detalle = detalle.replace(
                    settings.EMAIL_HOST_PASSWORD, "[contraseña omitida]"
                )
            raise CommandError(detalle) from None
        self.stdout.write(self.style.SUCCESS("Correo enviado"))
