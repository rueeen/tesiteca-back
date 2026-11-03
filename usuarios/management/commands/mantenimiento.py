import sys
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.db.models import Q
from django.utils import timezone
from usuarios.models import IntentoLogin, ImportacionLote, Usuario, EstadoCuenta
from notificaciones.models import TicketWS, Notificacion


def tamano_ruta(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        return 0
    if ruta.is_file():
        return ruta.stat().st_size
    # No seguir enlaces a directorios ajenos ni contar enlaces a archivos externos.
    return sum(
        archivo.stat().st_size
        for archivo in ruta.rglob("*")
        if not archivo.is_symlink() and archivo.is_file()
    )


class Command(BaseCommand):
    help = "Limpieza mensual de sesiones, datos temporales y diagnóstico de disco"

    def handle(self, *args, **opciones):
        ahora = timezone.now()
        call_command("flushexpiredtokens", stdout=self.stdout)
        self.stdout.write("Tokens JWT vencidos: limpieza completada")
        intentos = IntentoLogin.objects.filter(
            creado__lt=ahora - timedelta(days=30)
        ).delete()[0]
        cuentas = Usuario.objects.filter(
            estado_cuenta=EstadoCuenta.PENDIENTE_VERIFICACION,
            date_joined__lt=ahora - timedelta(days=7),
        ).delete()[0]
        tickets = TicketWS.objects.filter(
            Q(expira_en__lte=ahora) | Q(usado=True)
        ).delete()[0]
        archivos = 0
        for lote in (
            ImportacionLote.objects.filter(fecha__lt=ahora - timedelta(days=30))
            .exclude(archivo="")
            .iterator()
        ):
            lote.archivo.delete(save=True)
            archivos += 1
        notificaciones = Notificacion.objects.filter(
            leida=True, creada__lt=ahora - timedelta(days=180)
        ).delete()[0]
        self.stdout.write(
            f"Intentos eliminados: {intentos}; cuentas sin verificar eliminadas: {cuentas}; tickets eliminados: {tickets}; archivos de importación eliminados: {archivos}; notificaciones leídas eliminadas: {notificaciones}"
        )
        rutas = [
            ("Archivos privados", settings.PRIVATE_MEDIA_ROOT),
            ("SQLite", settings.DATABASES["default"]["NAME"]),
            ("Virtualenv", sys.prefix),
        ]
        total = 0
        for nombre, ruta in rutas:
            tamano = tamano_ruta(ruta)
            total += tamano
            self.stdout.write(f"{nombre}: {tamano / 1024**2:.2f} MiB")
        self.stdout.write(
            f"Total de los tres componentes: {total / 1024**2:.2f} MiB (no incluye código ni caché pip)"
        )
        if total > 400 * 1024**2:
            self.stdout.write(
                self.style.WARNING(
                    "AVISO: supera 400 MiB; la cuota total de la cuenta es 512 MiB"
                )
            )
