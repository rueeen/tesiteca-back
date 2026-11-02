from django.db import models
from tesis.almacenamiento import privado
from django.contrib.auth.models import AbstractUser, BaseUserManager


class Rol(models.TextChoices):
    ESTUDIANTE = "ESTUDIANTE", "Estudiante"
    COORDINADOR = "COORDINADOR", "Coordinador"
    DIRECTOR = "DIRECTOR", "Director"
    ADMIN = "ADMIN", "Administrador"


class GestorUsuario(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("El email es obligatorio")
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


class CodigoAcceso(models.Model):
    email = models.EmailField(db_index=True)
    codigo_hash = models.CharField(max_length=256)
    expira_en = models.DateTimeField()
    intentos = models.PositiveIntegerField(default=0)
    usado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
