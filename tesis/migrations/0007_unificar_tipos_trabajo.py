from django.db import migrations


def unificar_tipos(apps, schema_editor):
    Tesis = apps.get_model("tesis", "Tesis")
    Tesis.objects.filter(tipo__in=["TESIS", "INFORME_PRACTICA"]).update(
        tipo="PROYECTO_TITULO"
    )


class Migration(migrations.Migration):
    dependencies = [("tesis", "0006_renormalizar_resumen")]
    operations = [migrations.RunPython(unificar_tipos, migrations.RunPython.noop)]
