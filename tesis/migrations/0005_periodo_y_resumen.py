from django.db import migrations
import re


def normalizar_resumen(texto):
    lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parrafos = []
    actual = ""
    for linea in lineas:
        linea = re.sub(r"[^\S\n]+", " ", linea).strip()
        if not linea:
            if actual:
                parrafos.append(actual)
                actual = ""
            continue
        if not actual:
            actual = linea
        elif actual.endswith("-") and linea[0].islower():
            actual = actual[:-1] + linea
        elif actual.endswith((".", "!", "?", ":", ";")) or re.match(
            r"^(?:[-•*]|\d+[.)])(?:\s|$)", linea
        ):
            parrafos.append(actual)
            actual = linea
        else:
            actual += " " + linea
    if actual:
        parrafos.append(actual)
    return "\n\n".join(parrafos)


def normalizar_existentes(apps, schema_editor):
    Tesis = apps.get_model("tesis", "Tesis")
    for tesis in Tesis.objects.all().iterator():
        normalizado = normalizar_resumen(tesis.resumen)
        if normalizado != tesis.resumen:
            Tesis.objects.filter(pk=tesis.pk).update(resumen=normalizado)


class Migration(migrations.Migration):
    dependencies = [("tesis", "0004_alter_tesis_tipo")]
    operations = [
        migrations.RenameField(
            model_name="tesis", old_name="semestre", new_name="periodo"
        ),
        migrations.RunPython(normalizar_existentes, migrations.RunPython.noop),
    ]
