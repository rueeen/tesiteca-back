from django.db import models


class Region(models.TextChoices):
    XV = "XV", "Arica y Parinacota"
    I = "I", "Tarapacá"
    II = "II", "Antofagasta"
    III = "III", "Atacama"
    IV = "IV", "Coquimbo"
    V = "V", "Valparaíso"
    RM = "RM", "Metropolitana de Santiago"
    VI = "VI", "Libertador General Bernardo O'Higgins"
    VII = "VII", "Maule"
    XVI = "XVI", "Ñuble"
    VIII = "VIII", "Biobío"
    IX = "IX", "La Araucanía"
    XIV = "XIV", "Los Ríos"
    X = "X", "Los Lagos"
    XI = "XI", "Aysén del General Carlos Ibáñez del Campo"
    XII = "XII", "Magallanes y de la Antártica Chilena"


class NivelFormacion(models.TextChoices):
    TECNICO = "TECNICO", "Técnico de Nivel Superior"
    PROFESIONAL = "PROFESIONAL", "Profesional"
    INGENIERIA = "INGENIERIA", "Ingeniería"
