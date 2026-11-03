import csv
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from academico.models import Sede
from academico.opciones import Region
from academico.normalizacion import normalizar_nombre


class Command(BaseCommand):
    help = (
        "Importa sedes oficiales desde CSV; no contiene una lista de sedes predefinida"
    )

    def add_arguments(self, parser):
        parser.add_argument("archivo")

    def handle(self, *args, **opciones):
        regiones = {normalizar_nombre(n): c for c, n in Region.choices}
        regiones["xiii"] = "RM"
        regiones.update({c.casefold(): c for c, n in Region.choices})
        try:
            with open(opciones["archivo"], encoding="utf-8-sig", newline="") as entrada:
                lector = csv.DictReader(entrada)
                if lector.fieldnames != ["nombre", "ciudad", "region", "orden"]:
                    raise ValueError("Columnas esperadas: nombre,ciudad,region,orden")
                filas = list(lector)
            creadas = actualizadas = 0
            with transaction.atomic():
                for numero, fila in enumerate(filas, 2):
                    region = regiones.get(normalizar_nombre(fila["region"]))
                    if (
                        not region
                        or not fila["nombre"].strip()
                        or not fila["ciudad"].strip()
                    ):
                        raise ValueError(
                            f"Fila {numero}: nombre, ciudad o región inválidos"
                        )
                    orden = int(fila["orden"])
                    if orden < 0:
                        raise ValueError(f"Fila {numero}: orden debe ser positivo")
                    sede, nueva = Sede.objects.update_or_create(
                        nombre=fila["nombre"].strip(),
                        defaults={
                            "ciudad": fila["ciudad"].strip(),
                            "region": region,
                            "orden": orden,
                        },
                    )
                    if nueva:
                        creadas += 1
                    else:
                        actualizadas += 1
        except (OSError, ValueError, KeyError, csv.Error) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Sedes creadas: {creadas}; actualizadas: {actualizadas}")
