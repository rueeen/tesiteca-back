import logging
from django.core.management.base import BaseCommand, CommandError
from tesis.models import Tesis
from tesis.marca_agua import regenerar_marca

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Regenera las marcas fijas desde los originales privados, continuando ante errores"

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int)

    def handle(self, *args, **opciones):
        tesis = Tesis.objects.select_related("carrera").order_by("id")
        if opciones["id"] is not None:
            tesis = tesis.filter(pk=opciones["id"])
            if not tesis.exists():
                raise CommandError("La tesis indicada no existe")
        total = tesis.count()
        correctas = errores = 0
        for numero, registro in enumerate(tesis.iterator(), 1):
            try:
                regenerar_marca(registro)
                correctas += 1
                self.stdout.write(
                    f"[{numero}/{total}] Tesis {registro.id}: marca regenerada"
                )
            except Exception as exc:
                errores += 1
                logger.exception(
                    "No se pudo regenerar la marca de la tesis %s", registro.id
                )
                self.stderr.write(
                    f"[{numero}/{total}] Tesis {registro.id}: error {type(exc).__name__}"
                )
        self.stdout.write(
            f"Regeneradas: {correctas}; errores: {errores}; total: {total}"
        )
