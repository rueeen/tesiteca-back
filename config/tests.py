from usuarios.tests_helpers import crear_usuario_activo
import hashlib
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import jwt
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.management import call_command, CommandError
from django.http import JsonResponse, HttpResponse
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIRequestFactory
from usuarios.models import Usuario, IntentoLogin, ImportacionLote
from notificaciones.models import TicketWS, Notificacion
from tesis.views import ip_cliente
from .middleware import ProxyNetlifyMiddleware

SITIO = "https://otro-sitio.netlify.app"
CLAVE_PROXY = "secreto-de-prueba-para-firmas-netlify-" * 2


@override_settings(
    NETLIFY_PROXY_SECRET=CLAVE_PROXY, NETLIFY_SITE_URL=SITIO, EXIGIR_PROXY_NETLIFY=False
)
class ProxyTests(APITestCase):
    def setUp(self):
        cache.clear()

    def firma(self, **cambios):
        datos = {
            "iss": "netlify",
            "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
            "site_url": SITIO,
            "deploy_context": "production",
        }
        datos.update(cambios)
        return jwt.encode(datos, CLAVE_PROXY, algorithm="HS256")

    def consultar(self, firma=None, ip="203.0.113.17"):
        req = APIRequestFactory().get(
            "/api/prueba/",
            HTTP_X_NF_SIGN=firma or "",
            HTTP_X_NF_CLIENT_CONNECTION_IP=ip,
            REMOTE_ADDR="127.0.0.1",
        )
        middleware = ProxyNetlifyMiddleware(
            lambda r: JsonResponse({"proxy": r.via_proxy, "ip": ip_cliente(r)})
        )
        import json

        return json.loads(middleware(req).content)

    def test_firma_valida_ip_y_leeway(self):
        self.assertEqual(
            self.consultar(self.firma()), {"proxy": True, "ip": "203.0.113.17"}
        )
        self.assertTrue(
            self.consultar(self.firma(exp=int(timezone.now().timestamp()) - 10))[
                "proxy"
            ]
        )
        self.assertEqual(
            self.consultar(self.firma(), ip="falsa"), {"proxy": True, "ip": "127.0.0.1"}
        )

    def test_firmas_invalidas_no_permiten_falsificar_ip(self):
        firmas = [
            None,
            "invalida",
            self.firma(exp=int(timezone.now().timestamp()) - 60),
            self.firma(site_url="https://otro.test"),
            self.firma(deploy_context="deploy-preview"),
            self.firma(iss="otro"),
        ]
        payload = {
            "iss": "netlify",
            "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
            "site_url": SITIO,
            "deploy_context": "production",
        }
        firmas.extend(
            [
                jwt.encode(
                    payload, "otra-clave-suficientemente-larga-" * 2, algorithm="HS256"
                ),
                jwt.encode(payload, CLAVE_PROXY, algorithm="HS384"),
                jwt.encode(
                    {k: v for k, v in payload.items() if k != "exp"},
                    CLAVE_PROXY,
                    algorithm="HS256",
                ),
            ]
        )
        for firma in firmas:
            with self.subTest(firma=firmas.index(firma)):
                self.assertEqual(
                    self.consultar(firma), {"proxy": False, "ip": "127.0.0.1"}
                )

    @override_settings(EXIGIR_PROXY_NETLIFY=True)
    def test_bloqueo_api_excepcion_salud_y_admin(self):
        r = self.client.get("/api/tesis/")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(
            r.data if hasattr(r, "data") else r.json(),
            {"detail": "Acceso solo a través del sitio oficial"},
        )
        self.assertEqual(r["Cache-Control"], "no-store, private")
        self.assertEqual(self.client.get("/api/salud/").status_code, 200)
        self.assertEqual(
            self.client.get("/api/tesis/", HTTP_X_NF_SIGN=self.firma()).status_code, 401
        )
        for ruta in ["/admin/", "/static/prueba.css"]:
            req = APIRequestFactory().get(ruta)
            self.assertEqual(
                ProxyNetlifyMiddleware(lambda r: HttpResponse(status=200))(
                    req
                ).status_code,
                200,
            )

    def test_cache_api_y_preservacion_headers_explicitos(self):
        r = self.client.get("/api/tesis/")
        self.assertEqual(r["Cache-Control"], "no-store, private")
        self.assertTrue(
            {"authorization", "cookie"}.issubset(
                {v.strip().lower() for v in r["Vary"].split(",")}
            )
        )
        req = APIRequestFactory().get("/api/tesis/1/pdf/")
        response = HttpResponse(
            content_type="application/pdf",
            headers={
                "Cache-Control": "no-store",
                "Vary": "Origin",
                "X-Content-Type-Options": "nosniff",
            },
        )
        r = ProxyNetlifyMiddleware(lambda r: response)(req)
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("Origin", r["Vary"])

    def test_salud_no_expone_secretos_y_version_fallback(self):
        with (
            patch("config.views.version_git", return_value=None),
            override_settings(APP_VERSION="version-prueba"),
        ):
            r = self.client.get(
                "/api/salud/",
                HTTP_X_NF_SIGN=self.firma(),
                HTTP_AUTHORIZATION="Bearer no-importa",
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            set(r.data),
            {
                "estado",
                "version",
                "debug",
                "via_proxy",
                "notificaciones_ws",
                "correo",
                "base_datos",
                "politica_privacidad_version",
            },
        )
        self.assertEqual(r.data["estado"], "ok")
        self.assertEqual(r.data["base_datos"], "ok")
        self.assertTrue(r.data["via_proxy"])
        self.assertEqual(r.data["version"], "version-prueba")
        self.assertNotIn(settings.SECRET_KEY, r.content.decode())
        self.assertNotIn(CLAVE_PROXY, r.content.decode())

    def test_salud_throttle_30_por_minuto(self):
        for _ in range(30):
            self.assertEqual(self.client.get("/api/salud/").status_code, 200)
        self.assertEqual(self.client.get("/api/salud/").status_code, 429)


class ComandosDeployTests(APITestCase):
    def setUp(self):
        self.usuario = crear_usuario_activo(
            "mantenimiento@inacap.cl", nombre_completo="Mantenimiento", rol="ADMIN"
        )

    def test_mantenimiento_limpia_solo_datos_vencidos_y_archivo_importacion(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import (
            OutstandingToken,
            BlacklistedToken,
        )

        ahora = timezone.now()
        viejo = IntentoLogin.objects.create(
            email=self.usuario.email, ip="127.0.0.1", exitoso=False
        )
        IntentoLogin.objects.filter(pk=viejo.pk).update(
            creado=ahora - timedelta(days=31)
        )
        actual = IntentoLogin.objects.create(
            email=self.usuario.email, ip="127.0.0.1", exitoso=False
        )
        vencido = TicketWS.objects.create(
            usuario=self.usuario,
            ticket_hash="vencido",
            expira_en=ahora - timedelta(seconds=1),
        )
        usado = TicketWS.objects.create(
            usuario=self.usuario,
            ticket_hash="usado",
            expira_en=ahora + timedelta(minutes=1),
            usado=True,
        )
        vigente = TicketWS.objects.create(
            usuario=self.usuario,
            ticket_hash="vigente",
            expira_en=ahora + timedelta(minutes=1),
        )
        leida = Notificacion.objects.create(
            usuario=self.usuario,
            tipo="TESIS_APROBADA",
            titulo="Leída",
            mensaje="",
            enlace="/",
            leida=True,
        )
        no_leida = Notificacion.objects.create(
            usuario=self.usuario,
            tipo="TESIS_APROBADA",
            titulo="No leída",
            mensaje="",
            enlace="/",
        )
        reciente = Notificacion.objects.create(
            usuario=self.usuario,
            tipo="TESIS_APROBADA",
            titulo="Reciente",
            mensaje="",
            enlace="/",
            leida=True,
        )
        Notificacion.objects.filter(pk__in=[leida.pk, no_leida.pk]).update(
            creada=ahora - timedelta(days=181)
        )
        token = RefreshToken.for_user(self.usuario)
        token.blacklist()
        OutstandingToken.objects.filter(jti=token["jti"]).update(
            expires_at=ahora - timedelta(seconds=1)
        )
        with tempfile.TemporaryDirectory() as carpeta:
            from django.core.files.storage import FileSystemStorage

            storage = FileSystemStorage(location=carpeta)
            with patch.object(
                ImportacionLote._meta.get_field("archivo"), "storage", storage
            ):
                lote = ImportacionLote.objects.create(
                    creado_por=self.usuario,
                    archivo=ContentFile(b"RUT y correo", name="viejo.csv"),
                )
                vigente_lote = ImportacionLote.objects.create(
                    creado_por=self.usuario,
                    archivo=ContentFile(b"reciente", name="reciente.csv"),
                )
                nombre = lote.archivo.name
                ImportacionLote.objects.filter(pk=lote.pk).update(
                    fecha=ahora - timedelta(days=31)
                )
                salida = StringIO()
                for _ in range(2):
                    with patch(
                        "usuarios.management.commands.mantenimiento.tamano_ruta",
                        return_value=150 * 1024**2,
                    ):
                        call_command("mantenimiento", stdout=salida)
                self.assertFalse(storage.exists(nombre))
                self.assertTrue(storage.exists(vigente_lote.archivo.name))
                lote.refresh_from_db()
                self.assertFalse(lote.archivo)
                self.assertIn("400 MiB", salida.getvalue())
        self.assertEqual(
            list(IntentoLogin.objects.values_list("pk", flat=True)), [actual.pk]
        )
        self.assertEqual(
            list(TicketWS.objects.values_list("pk", flat=True)), [vigente.pk]
        )
        self.assertEqual(
            set(Notificacion.objects.values_list("pk", flat=True)),
            {no_leida.pk, reciente.pk},
        )
        self.assertFalse(OutstandingToken.objects.filter(jti=token["jti"]).exists())
        self.assertEqual(BlacklistedToken.objects.count(), 0)

    def test_verificar_deploy_desarrollo_falla_y_produccion_pasa(self):
        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command("verificar_deploy", stdout=StringIO())
        with tempfile.TemporaryDirectory() as carpeta:
            privado = Path(carpeta) / "privado"
            privado.mkdir()
            static = Path(carpeta) / "static"
            (static / "admin").mkdir(parents=True)
            salida = StringIO()
            with override_settings(
                DEBUG=False,
                FRONTEND_URL=SITIO,
                SECRET_KEY="clave-segura-de-prueba-" * 4,
                ALLOWED_HOSTS=["rvavalencia.pythonanywhere.com"],
                CSRF_TRUSTED_ORIGINS=[SITIO, "https://rvavalencia.pythonanywhere.com"],
                SECURE_COOKIES=True,
                EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                EMAIL_HOST="smtp.gmail.com",
                EMAIL_HOST_USER="demo@gmail.com",
                EMAIL_HOST_PASSWORD="password-prueba",
                NETLIFY_PROXY_SECRET=CLAVE_PROXY,
                NETLIFY_SITE_URL=SITIO,
                EXIGIR_PROXY_NETLIFY=True,
                NOTIFICACIONES_WS=False,
                PRIVATE_MEDIA_ROOT=privado,
                STATIC_ROOT=static,
            ):
                call_command("verificar_deploy", stdout=salida)
                self.assertNotIn("password-prueba", salida.getvalue())
                self.assertNotIn(CLAVE_PROXY, salida.getvalue())
                for cambios in [
                    {"PRIVATE_MEDIA_ROOT": static / "admin"},
                    {"NETLIFY_PROXY_SECRET": ""},
                    {"FRONTEND_URL": "http://otro-sitio.netlify.app"},
                    {"ALLOWED_HOSTS": []},
                    {"ALLOWED_HOSTS": ["backend-incorrecto.test"]},
                    {"CSRF_TRUSTED_ORIGINS": [SITIO]},
                ]:
                    with override_settings(**cambios), self.assertRaises(CommandError):
                        call_command("verificar_deploy", stdout=StringIO())
                distinto = "https://sitio-equivocado.netlify.app"
                mensaje = StringIO()
                with (
                    override_settings(NETLIFY_SITE_URL=distinto),
                    self.assertRaises(CommandError),
                ):
                    call_command("verificar_deploy", stdout=mensaje)
                self.assertIn(distinto, mensaje.getvalue())
                self.assertIn(SITIO, mensaje.getvalue())
                with override_settings(
                    ALLOWED_HOSTS=["backend-prueba.test"],
                    CSRF_TRUSTED_ORIGINS=[SITIO, "https://backend-prueba.test"],
                ):
                    call_command("verificar_deploy", stdout=StringIO())
                with patch(
                    "usuarios.management.commands.verificar_deploy.MigrationExecutor"
                ) as ejecutor:
                    ejecutor.return_value.migration_plan.return_value = ["pendiente"]
                    with self.assertRaises(CommandError):
                        call_command("verificar_deploy", stdout=StringIO())


class RenderersTests(APITestCase):
    def test_renderers_de_produccion_y_desarrollo(self):
        # Arrancar Django en procesos independientes para probar la configuración
        # real de DEBUG antes de que DRF cargue sus clases por defecto.
        import json
        import os
        import subprocess
        import sys

        codigo = """
import json
import django
django.setup()
from django.conf import settings
from django.db import connection
from django.test import Client
from rest_framework.views import APIView
connection.settings_dict['NAME'] = ':memory:'
cliente = Client()
html = cliente.get('/api/salud/', HTTP_ACCEPT='text/html')
api = cliente.get('/api/salud/', HTTP_ACCEPT='application/json')
print(json.dumps({'html_status': html.status_code, 'html_content_type': html['Content-Type'], 'api_status': api.status_code, 'api_estado': api.json()['estado'], 'renderers': [r.__name__ for r in APIView.renderer_classes], 'html_es_json': html['Content-Type'].startswith('application/json')}))
"""
        for debug in ["False", "True"]:
            with self.subTest(DEBUG=debug):
                entorno = {
                    **os.environ,
                    "DJANGO_SETTINGS_MODULE": "config.settings",
                    "DEBUG": debug,
                    "ALLOWED_HOSTS": "testserver",
                    "SECURE_SSL_REDIRECT": "False",
                    "EXIGIR_PROXY_NETLIFY": "False",
                }
                resultado = subprocess.run(
                    [sys.executable, "-c", codigo],
                    cwd=settings.BASE_DIR,
                    env=entorno,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(resultado.returncode, 0, resultado.stderr)
                datos = json.loads(resultado.stdout)
                self.assertEqual(datos["api_status"], 200)
                self.assertEqual(datos["api_estado"], "ok")
                if debug == "False":
                    self.assertEqual(datos["renderers"], ["JSONRenderer"])
                    self.assertEqual(datos["html_status"], 406)
                    self.assertTrue(datos["html_es_json"])
                else:
                    self.assertIn("BrowsableAPIRenderer", datos["renderers"])
                    self.assertEqual(datos["html_status"], 200)
                    self.assertTrue(datos["html_content_type"].startswith("text/html"))
