from getpass import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from usuarios.models import Usuario, UsuarioAutorizado, Rol, EstadoCuenta
from usuarios.cuentas import revocar_sesiones


class Command(BaseCommand):
    help = "Crea o actualiza el ADMIN inicial con contraseña privada"

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--nombre")

    @transaction.atomic
    def handle(self, *args, **opciones):
        email = opciones["email"].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Email inválido") from exc
        if email.rsplit("@", 1)[-1] != "inacap.cl":
            raise CommandError("ADMIN debe usar correo @inacap.cl")
        nombre = opciones.get("nombre") or input("Nombre completo: ").strip()
        if not nombre:
            raise CommandError("El nombre es obligatorio")
        usuario = Usuario.objects.filter(email=email).first() or Usuario(email=email)
        usuario.nombre_completo = nombre
        password = getpass("Contraseña: ")
        confirmacion = getpass("Repite la contraseña: ")
        if password != confirmacion:
            raise CommandError("Las contraseñas no coinciden")
        try:
            validate_password(password, usuario)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        usuario.rol = Rol.ADMIN
        usuario.estado_cuenta = EstadoCuenta.ACTIVA
        usuario.email_verificado_en = timezone.now()
        usuario.is_staff = True
        usuario.is_superuser = True
        usuario.set_password(password)
        usuario.save()
        revocar_sesiones(usuario)
        UsuarioAutorizado.objects.update_or_create(
            email=email,
            defaults={"nombre_completo": nombre, "rol": Rol.ADMIN, "activo": True},
        )
        self.stdout.write(self.style.SUCCESS("Administrador activo creado/actualizado"))
