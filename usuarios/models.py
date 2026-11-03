from django.db import models
from tesis.almacenamiento import privado
from django.contrib.auth.models import AbstractUser, BaseUserManager


class Rol(models.TextChoices):
    ESTUDIANTE = "ESTUDIANTE", "Estudiante"
    COORDINADOR = "COORDINADOR", "Coordinador"
    DIRECTOR = "DIRECTOR", "Director"
    ADMIN = "ADMIN", "Administrador"


class EstadoCuenta(models.TextChoices):
    PENDIENTE_VERIFICACION = "PENDIENTE_VERIFICACION", "Pendiente de verificación"
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION", "Pendiente de aprobación"
    ACTIVA = "ACTIVA", "Activa"
    RECHAZADA = "RECHAZADA", "Rechazada"
    DESACTIVADA = "DESACTIVADA", "Desactivada"


class GestorUsuario(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("El email es obligatorio")
        if extra.get("estado_cuenta", EstadoCuenta.ACTIVA) == EstadoCuenta.ACTIVA:
            from django.utils import timezone

            extra.setdefault("email_verificado_en", timezone.now())
        usuario = self.model(email=email.strip().lower(), **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("rol", Rol.ADMIN)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("El superusuario debe tener permisos administrativos")
        return self.create_user(email, password, **extra)


class DatosPersona(models.Model):
    email = models.EmailField(unique=True)
    rut = models.CharField(max_length=20, blank=True)
    nombre_completo = models.CharField(max_length=200)
    rol = models.CharField(max_length=20, choices=Rol.choices, default=Rol.ESTUDIANTE)
    carrera = models.ForeignKey(
        "academico.Carrera", on_delete=models.PROTECT, null=True, blank=True
    )
    area = models.ForeignKey(
        "academico.Area", on_delete=models.PROTECT, null=True, blank=True
    )
    sede = models.ForeignKey(
        "academico.Sede", on_delete=models.PROTECT, null=True, blank=True
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class Usuario(AbstractUser, DatosPersona):
    username = None
    email = models.EmailField(unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nombre_completo"]
    objects = GestorUsuario()
    estado_cuenta = models.CharField(
        max_length=30, choices=EstadoCuenta.choices, default=EstadoCuenta.ACTIVA
    )
    email_verificado_en = models.DateTimeField(null=True, blank=True)
    ultimo_envio_verificacion = models.DateTimeField(null=True, blank=True)
    contador_envios_verificacion = models.PositiveSmallIntegerField(default=0)
    inicio_envios_verificacion = models.DateTimeField(null=True, blank=True)
    inicio_recuperaciones = models.DateTimeField(null=True, blank=True)
    contador_recuperaciones = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rut"],
                condition=~models.Q(rut=""),
                name="rut_usuario_unico_no_vacio",
            ),
            models.CheckConstraint(
                condition=models.Q(rol="ADMIN") | models.Q(sede__isnull=False),
                name="sede_obligatoria_no_admin",
            ),
        ]

    def clean(self):
        super().clean()
        if self.rol != Rol.ADMIN and not self.sede_id:
            from django.core.exceptions import ValidationError

            raise ValidationError({"sede": "La sede es obligatoria para este rol"})

    def cambiar_estado(self, estado):
        self.estado_cuenta = estado
        self.is_active = estado == EstadoCuenta.ACTIVA
        self.save(update_fields=["estado_cuenta", "is_active"])

    def save(self, *args, **kwargs):
        self.is_active = self.estado_cuenta == EstadoCuenta.ACTIVA
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"is_active"}
        super().save(*args, **kwargs)


class ImportacionLote(models.Model):
    archivo = models.FileField(upload_to="importaciones/", storage=privado)
    creado_por = models.ForeignKey("Usuario", on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    total_filas = models.PositiveIntegerField(default=0)
    creados = models.PositiveIntegerField(default=0)
    actualizados = models.PositiveIntegerField(default=0)
    errores = models.JSONField(default=list)


class UsuarioAutorizado(DatosPersona):
    activo = models.BooleanField(default=True)
    lote = models.ForeignKey(
        ImportacionLote, on_delete=models.SET_NULL, null=True, blank=True
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)


class SolicitudAcceso(models.Model):
    usuario = models.OneToOneField(
        Usuario, on_delete=models.CASCADE, related_name="solicitud"
    )
    rol_solicitado = models.CharField(max_length=20, choices=Rol.choices)
    carrera = models.ForeignKey(
        "academico.Carrera", on_delete=models.PROTECT, null=True, blank=True
    )
    sede = models.ForeignKey("academico.Sede", on_delete=models.PROTECT)
    mensaje = models.CharField(max_length=500, blank=True)
    estado = models.CharField(
        max_length=15,
        choices=[
            ("PENDIENTE", "Pendiente"),
            ("APROBADA", "Aprobada"),
            ("RECHAZADA", "Rechazada"),
        ],
        default="PENDIENTE",
    )
    motivo_rechazo = models.CharField(max_length=300, blank=True)
    revisada_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitudes_revisadas",
    )
    revisada_en = models.DateTimeField(null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creada", "-id"]


class IntentoLogin(models.Model):
    email = models.EmailField()
    ip = models.GenericIPAddressField(null=True)
    exitoso = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["email", "creado"])]
