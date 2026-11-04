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

    def test_renormalizar_desde_0005_aplicada(self):
        codigo = """
import os, json
from pathlib import Path
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
connection.settings_dict['NAME'] = os.environ['PRUEBA_MIGRACION_DB']
ejecutor = MigrationExecutor(connection)
previas = [('tesis', '0005_periodo_y_resumen'), ('usuarios', '0003_usuario_sede_obligatoria_no_admin'), ('academico', '0002_alter_sede_options_carrera_duracion_semestres_and_more')]
ejecutor.migrate(previas)
apps = ejecutor.loader.project_state(previas).apps
sede = apps.get_model('academico', 'Sede').objects.create(nombre='Arica', ciudad='Arica')
area = apps.get_model('academico', 'Area').objects.create(nombre='Informática')
carrera = apps.get_model('academico', 'Carrera').objects.create(nombre='Ingeniería', codigo='IEI', area=area)
u = apps.get_model('usuarios', 'Usuario').objects.create(email='migracion@inacap.cl', nombre_completo='Admin de prueba', rol='ADMIN')
casos = json.loads(Path('tesis/tests_fixtures/resumen_casos.json').read_text())
Tesis = apps.get_model('tesis', 'Tesis')
for i, caso in enumerate(casos):
    Tesis.objects.create(titulo=caso['id'], resumen=caso['entrada'], tipo='TESIS', anio=2026, periodo=2, carrera=carrera, sede=sede, subido_por=u, profesor_guia='Guía', pdf_original=f'IEI/{i}.pdf', pdf_marcado=f'IEI/{i}-marcado.pdf', hash_sha256=f'{i:064x}')
ejecutor = MigrationExecutor(connection)
ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
from tesis.models import Tesis as TesisActual
for caso in casos:
    tesis = TesisActual.objects.get(titulo=caso['id'])
    assert tesis.resumen == caso['esperado'], caso['id']
    assert tesis.periodo == 2
assert TesisActual.objects.count() == 10
# La función congelada se puede reaplicar sin modificar los resultados.
from importlib import import_module
migracion = import_module('tesis.migrations.0006_renormalizar_resumen')
migracion.renormalizar(ejecutor.loader.project_state(ejecutor.loader.graph.leaf_nodes()).apps, None)
for caso in casos:
    assert TesisActual.objects.get(titulo=caso['id']).resumen == caso['esperado']
"""
        with tempfile.TemporaryDirectory() as carpeta:
            entorno = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "PRUEBA_MIGRACION_DB": str(Path(carpeta) / "version_0005.sqlite3"),
            }
            resultado = subprocess.run(
                [sys.executable, "-c", codigo],
                cwd=settings.BASE_DIR,
                env=entorno,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_migracion_legadas_correo_y_aprobacion(self):
        codigo = """
import os
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
connection.settings_dict['NAME'] = os.environ['PRUEBA_MIGRACION_DB']
ejecutor = MigrationExecutor(connection)
previas = [('usuarios','0003_usuario_sede_obligatoria_no_admin'), ('academico','0002_alter_sede_options_carrera_duracion_semestres_and_more')]
ejecutor.migrate(previas)
apps = ejecutor.loader.project_state(previas).apps
Usuario = apps.get_model('usuarios','Usuario')
u=Usuario.objects.create(email='legada@inacap.cl',nombre_completo='Legada',rol='ADMIN',estado_cuenta='ACTIVA',is_active=True,email_verificado_en=None)
p=Usuario.objects.create(email='pendiente@inacap.cl',nombre_completo='Pendiente',rol='ADMIN',estado_cuenta='PENDIENTE_VERIFICACION',is_active=False,email_verificado_en=None)
ejecutor = MigrationExecutor(connection)
ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
from usuarios.models import Usuario, SolicitudAcceso
actual=Usuario.objects.get(pk=u.pk)
assert actual.email_verificado_en is not None and actual.estado_cuenta=='ACTIVA'
aprobada=SolicitudAcceso.objects.get(usuario=actual)
assert aprobada.estado=='APROBADA' and aprobada.revisada_por_id is None and aprobada.motivo_rechazo=='' and aprobada.mensaje=='Cuenta legada'
assert Usuario.objects.get(pk=p.pk).email_verificado_en is None
assert not SolicitudAcceso.objects.filter(usuario_id=p.pk).exists()
"""
        with tempfile.TemporaryDirectory() as carpeta:
            entorno = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "PRUEBA_MIGRACION_DB": str(Path(carpeta) / "legadas.sqlite3"),
            }
            resultado = subprocess.run(
                [sys.executable, "-c", codigo],
                cwd=settings.BASE_DIR,
                env=entorno,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_migracion_tipos_trabajo_conserva_datos_y_reversa_esquema(self):
        codigo = """
import os
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
connection.settings_dict['NAME']=os.environ['PRUEBA_MIGRACION_DB']
ejecutor=MigrationExecutor(connection)
previas=[('tesis','0006_renormalizar_resumen'),('usuarios','0004_alter_solicitudacceso_sede_and_more'),('academico','0002_alter_sede_options_carrera_duracion_semestres_and_more')]
ejecutor.migrate(previas)
apps=ejecutor.loader.project_state(previas).apps
sede=apps.get_model('academico','Sede').objects.create(nombre='Arica',ciudad='Arica')
area=apps.get_model('academico','Area').objects.create(nombre='Informática')
carrera=apps.get_model('academico','Carrera').objects.create(nombre='Ingeniería',codigo='IEI',area=area)
u=apps.get_model('usuarios','Usuario').objects.create(email='migracion-tipos@inacap.cl',nombre_completo='Autor',rol='ADMIN')
Tesis=apps.get_model('tesis','Tesis')
ids=[]
for i,tipo in enumerate(['TESIS','INFORME_PRACTICA','PROYECTO_TITULO']):
    tesis=Tesis.objects.create(titulo=f'Trabajo anterior {i}',resumen='Resumen conservado',tipo=tipo,anio=2026,periodo=2,carrera=carrera,sede=sede,subido_por=u,profesor_guia='Guía',pdf_original=f'IEI/{i}.pdf',pdf_marcado=f'IEI/{i}-marca.pdf',hash_sha256=f'{i:064x}')
    ids.append(tesis.pk)
ejecutor=MigrationExecutor(connection)
ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
from tesis.models import Tesis as Actual, TipoTrabajo
assert Actual.objects.count()==3
assert set(Actual.objects.values_list('tipo',flat=True))=={TipoTrabajo.PROYECTO_TITULO}
for i,pk in enumerate(ids):
    tesis=Actual.objects.get(pk=pk)
    assert tesis.pdf_original.name==f'IEI/{i}.pdf' and tesis.periodo==2 and tesis.resumen=='Resumen conservado'
# Solo se revierte el esquema; la normalización de datos no inventa el tipo anterior.
ejecutor=MigrationExecutor(connection)
ejecutor.migrate([('tesis','0006_renormalizar_resumen')])
apps=ejecutor.loader.project_state([('tesis','0006_renormalizar_resumen')]).apps
Anterior=apps.get_model('tesis','Tesis')
assert ('TESIS','Tesis') in Anterior._meta.get_field('tipo').choices
assert set(Anterior.objects.values_list('tipo',flat=True))=={'PROYECTO_TITULO'}
"""
        with tempfile.TemporaryDirectory() as carpeta:
            entorno = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "PRUEBA_MIGRACION_DB": str(Path(carpeta) / "tipos.sqlite3"),
            }
            resultado = subprocess.run(
                [sys.executable, "-c", codigo],
                cwd=settings.BASE_DIR,
                env=entorno,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
