from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from privacidad.anonimizacion import (
    lecturas_antiguas,
    rechazadas_antiguas,
    cuentas_inactivas,
    anonimizar_lecturas_antiguas,
    limpiar_solicitudes_rechazadas,
    limpiar_cuentas_inactivas,
)


class Command(BaseCommand):
    help = "Aplica la retención de privacidad; --dry-run solo cuenta, sin escribir ni borrar archivos"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        plazos = [
            settings.RETENCION_LECTURAS_DIAS,
            settings.RETENCION_SOLICITUDES_RECHAZADAS_DIAS,
            settings.RETENCION_CUENTAS_INACTIVAS_DIAS,
        ]
        if any(d < 0 for d in plazos):
            raise CommandError(
                "Los plazos de retención deben ser cero (desactivado) o positivos"
            )
        consultas = [lecturas_antiguas, rechazadas_antiguas, cuentas_inactivas]
        acciones = [
            anonimizar_lecturas_antiguas,
            limpiar_solicitudes_rechazadas,
            limpiar_cuentas_inactivas,
        ]
        if options["dry_run"]:
            cantidades = [
                consulta(dias).count() for consulta, dias in zip(consultas, plazos)
            ]
        else:
            cantidades = [accion(dias) for accion, dias in zip(acciones, plazos)]
        prefijo = (
            "Simulación (sin cambios)"
            if options["dry_run"]
            else "Anonimización completada"
        )
        self.stdout.write(
            f"{prefijo}: lecturas={cantidades[0]}; rechazadas={cantidades[1]}; inactivas={cantidades[2]}"
        )
