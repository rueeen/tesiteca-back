import ipaddress
from django.db import migrations
from django.db.models import Q


def minimizar_y_marcar_legado(apps, schema_editor):
    base = schema_editor.connection.alias
    Tesis = apps.get_model("tesis", "Tesis")
    Tesis.objects.using(base).all().update(
        autoriza_publicacion=True, autorizacion_version="legado"
    )
    Tesis.objects.using(base).filter(
        Q(estado="PUBLICADA") | Q(fecha_publicacion__isnull=False)
    ).update(publicada_alguna_vez=True)
    # Evidencia histórica de aprobaciones aunque el trabajo haya vuelto a revisión.
    Notificacion = apps.get_model("notificaciones", "Notificacion")
    for aviso in (
        Notificacion.objects.using(base).filter(tipo="TESIS_APROBADA").iterator()
    ):
        tesis_id = (
            aviso.datos.get("tesis_id") if isinstance(aviso.datos, dict) else None
        )
        if isinstance(tesis_id, int):
            Tesis.objects.using(base).filter(pk=tesis_id).update(
                publicada_alguna_vez=True
            )
    Registro = apps.get_model("tesis", "RegistroAcceso")
    for registro in Registro.objects.using(base).all().iterator():
        try:
            ip = ipaddress.ip_address(registro.ip)
            truncada = str(
                ipaddress.ip_network(
                    f"{ip}/{24 if ip.version == 4 else 48}", strict=False
                ).network_address
            )
        except (ValueError, TypeError):
            truncada = None
        # No conservar los agentes históricos completos.
        Registro.objects.using(base).filter(pk=registro.pk).update(
            ip=truncada, user_agent=""
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tesis", "0009_tesis_autoriza_publicacion_tesis_autorizacion_en_and_more"),
        ("notificaciones", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(minimizar_y_marcar_legado, migrations.RunPython.noop)
    ]
