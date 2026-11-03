import os
import subprocess
import sys
import tempfile
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase


class MigracionCuentasTests(SimpleTestCase):
    def test_actualizacion_desde_base_anterior_preserva_datos(self):
        codigo = """
import os
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.contrib.auth.hashers import make_password
connection.settings_dict['NAME']=os.environ['PRUEBA_MIGRACION_DB']
ejecutor=MigrationExecutor(connection)
anteriores=[('academico','0001_initial'),('usuarios','0001_initial'),('tesis','0004_alter_tesis_tipo'),('notificaciones','0001_initial'),('token_blacklist','0013_alter_blacklistedtoken_options_and_more')]
ejecutor.migrate(anteriores)
apps=ejecutor.loader.project_state(anteriores).apps
sede=apps.get_model('academico','Sede').objects.create(nombre='Arica',ciudad='Arica')
area=apps.get_model('academico','Area').objects.create(nombre='Informática')
carrera=apps.get_model('academico','Carrera').objects.create(nombre='Ingeniería',codigo='IEI',area=area)
u=apps.get_model('usuarios','Usuario').objects.create(email='anterior@inacapmail.cl',nombre_completo='Anterior',password=make_password(None),rol='ESTUDIANTE',sede=sede,carrera=carrera,is_active=True)
t=apps.get_model('tesis','Tesis').objects.create(titulo='Anterior',resumen='Esta infor-\\nmación quedó cortada.\\nOtro párrafo.',tipo='TESIS',anio=2026,semestre=2,carrera=carrera,sede=sede,subido_por=u,profesor_guia='Guía',pdf_original='IEI/original.pdf',pdf_marcado='IEI/marcado.pdf',hash_sha256='1'*64)
apps.get_model('tesis','AutorTesis').objects.create(tesis=t,usuario=u,nombre_completo='Anterior')
ejecutor=MigrationExecutor(connection)
ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
from usuarios.models import Usuario
from tesis.models import Tesis
from academico.models import Carrera
nuevo=Usuario.objects.get(pk=u.pk);tesis=Tesis.objects.get(pk=t.pk)
assert nuevo.estado_cuenta=='ACTIVA' and nuevo.is_active and nuevo.email_verificado_en
assert not nuevo.has_usable_password()
assert tesis.periodo==2 and tesis.pdf_original.name=='IEI/original.pdf'
assert tesis.resumen=='Esta información quedó cortada.\\n\\nOtro párrafo.'
assert tesis.autores.get().usuario_id==u.pk
assert Carrera.objects.get(pk=carrera.pk).duracion_semestres==8
print('Migración anterior → actual sin pérdida de usuarios, autorías, PDF ni período')
"""
        with tempfile.TemporaryDirectory() as carpeta:
            env = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "PRUEBA_MIGRACION_DB": str(Path(carpeta) / "anterior.sqlite3"),
            }
            resultado = subprocess.run(
                [sys.executable, "-c", codigo],
                cwd=settings.BASE_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
