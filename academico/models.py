from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from .opciones import Region, NivelFormacion


class Sede(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    ciudad = models.CharField(max_length=150)
    region = models.CharField(max_length=4, choices=Region.choices, default=Region.XV)
    orden = models.PositiveIntegerField(default=1)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Area(models.Model):
    nombre = models.CharField(max_length=200, unique=True)
    activa = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class Carrera(models.Model):
    nombre = models.CharField(max_length=200)
    codigo = models.CharField(max_length=30, unique=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT)
    activa = models.BooleanField(default=True)
    permite_repositorio = models.BooleanField(default=False)
    nivel_formacion = models.CharField(
        max_length=20,
        choices=NivelFormacion.choices,
        default=NivelFormacion.PROFESIONAL,
    )
    duracion_semestres = models.PositiveSmallIntegerField(
        default=8, validators=[MinValueValidator(2), MaxValueValidator(10)]
    )
    extensiones_material = models.CharField(max_length=200, default=".pdf")

    def __str__(self):
        return self.nombre

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    duracion_semestres__gte=2, duracion_semestres__lte=10
                ),
                name="duracion_entre_2_y_10",
            )
        ]
