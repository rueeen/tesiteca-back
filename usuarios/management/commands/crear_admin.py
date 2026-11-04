from getpass import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from usuarios.models import Usuario, UsuarioAutorizado, Rol, EstadoCuenta
from usuarios.cuentas import (
    revocar_sesiones,
    aprobar_cuenta,
    enviar_verificacion,
    puede_iniciar_sesion,
)


class Command(BaseCommand):
    help = "Crea o actualiza el ADMIN inicial con contraseña privada"

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--nombre")
        parser.add_argument(
            "--sin-verificar",
            action="store_true",
            help="Emergencia: omite el enlace de correo de forma explícita",
        )

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
        estaba_activa = puede_iniciar_sesion(usuario)
        usuario.set_password(password)
        if estaba_activa:
            usuario.save(update_fields=["nombre_completo", "password"])
            revocar_sesiones(usuario)
            self.stdout.write(
                self.style.SUCCESS(
                    "Administrador actualizado; conserva el correo validado"
                )
            )
            return
        usuario.rol = Rol.ADMIN
        usuario.estado_cuenta = EstadoCuenta.PENDIENTE_VERIFICACION
        usuario.is_staff = True
        usuario.is_superuser = True
        usuario.email_verificado_en = (
            timezone.now() if opciones["sin_verificar"] else None
        )
        usuario.save()
        revocar_sesiones(usuario)
        aprobar_cuenta(
            usuario,
            {
                "rol": Rol.ADMIN,
                "carrera": usuario.carrera,
                "area": usuario.area,
                "sede": usuario.sede,
            },
            mensaje="Creado por consola",
        )
        if opciones["sin_verificar"]:
            self.stdout.write(
                self.style.WARNING(
                    "ADVERTENCIA: correo marcado como validado por excepción de emergencia (--sin-verificar)"
                )
            )
        else:
            enviar_verificacion(usuario)
            self.stdout.write("Revisa tu correo para validar la cuenta")
