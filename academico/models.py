from django.db import models


class Sede(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    ciudad = models.CharField(max_length=150)
    activa = models.BooleanField(default=True)

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
    extensiones_material = models.CharField(max_length=200, default=".pdf")

    def __str__(self):
        return self.nombre
