from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from academico.models import Area, Carrera, Sede
from .models import Usuario, UsuarioAutorizado, EstadoCuenta, Rol


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CSRF_TRUSTED_ORIGINS=["https://front.test"],
)
class SeguridadTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.sede = Sede.objects.create(nombre="Arica", ciudad="Arica")
        area = Area.objects.create(nombre="Informática")
        carrera = Carrera.objects.create(nombre="Informática", codigo="IEI", area=area)
        datos = {"nombre_completo": "Estudiante", "carrera": carrera, "sede": self.sede}
        self.usuario = Usuario.objects.create_user("alumno@inacapmail.cl", **datos)
        self.autorizado = UsuarioAutorizado.objects.create(
            email=self.usuario.email, **datos
        )
        self.admin = Usuario.objects.create_user(
            "admin@inacap.cl", rol=Rol.ADMIN, nombre_completo="Admin"
        )

    def iniciar(self):
        self.usuario.set_password("Clave-prueba-segura-2026")
        self.usuario.save()
        r = self.client.post(
            "/api/auth/login/",
            {"email": self.usuario.email, "password": "Clave-prueba-segura-2026"},
        )
        self.assertEqual(r.status_code, 200, r.data)
        return r

    def renovar(self, **headers):
        return self.client.post(
            "/api/auth/refresh/", HTTP_X_REQUESTED_WITH="XMLHttpRequest", **headers
        )

    def test_login_cookie_y_ultima_entrada(self):
        with override_settings(SECURE_COOKIES=True):
            r = self.iniciar()
        self.assertEqual(set(r.data), {"access", "usuario"})
        cookie = r.cookies[settings.REFRESH_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/auth/")
        self.assertEqual(cookie["max-age"], 7 * 24 * 3600)
        self.usuario.refresh_from_db()
        self.assertIsNotNone(self.usuario.last_login)

    def test_refresh_rota_y_rechaza_reuso(self):
        r = self.iniciar()
        anterior = r.cookies[settings.REFRESH_COOKIE_NAME].value
        jti = RefreshToken(anterior)["jti"]
        r = self.renovar(HTTP_ORIGIN="https://front.test")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(set(r.data), {"access", "usuario"})
        nuevo = r.cookies[settings.REFRESH_COOKIE_NAME].value
        self.assertNotEqual(anterior, nuevo)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=jti).exists())
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = anterior
        self.assertEqual(self.renovar().status_code, 401)

    def test_cookie_ignora_body_y_falta_cookie(self):
        sin_cookie = self.renovar()
        self.assertEqual(sin_cookie.status_code, 204)
        self.assertEqual(sin_cookie.content, b"")
        token = str(RefreshToken.for_user(self.usuario))
        r = self.client.post(
            "/api/auth/refresh/",
            {"refresh": token},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.content, b"")
        self.assertIsNone(r.data)
        self.iniciar()
        r = self.client.post(
            "/api/auth/refresh/",
            {"refresh": "invalido"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = "invalido"
        r = self.renovar()
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.cookies[settings.REFRESH_COOKIE_NAME]["max-age"], 0)
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = ""
        vacia = self.renovar()
        self.assertEqual(vacia.status_code, 401)
        self.assertEqual(vacia.cookies[settings.REFRESH_COOKIE_NAME]["max-age"], 0)

    def test_csrf_refresh_y_logout(self):
        self.assertEqual(self.client.post("/api/auth/refresh/").status_code, 403)
        self.assertEqual(
            self.renovar(HTTP_ORIGIN="https://maligno.test").status_code, 403
        )
        self.iniciar()
        for ruta in ["/api/auth/refresh/", "/api/auth/logout/"]:
            self.assertEqual(self.client.post(ruta).status_code, 403)
            self.assertEqual(
                self.client.post(
                    ruta,
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                    HTTP_ORIGIN="https://maligno.test",
                ).status_code,
                403,
            )

    def test_logout_revoca_y_funciona_con_access_vencido(self):
        r = self.iniciar()
        raw = r.cookies[settings.REFRESH_COOKIE_NAME].value
        jti = RefreshToken(raw)["jti"]
        self.client.credentials(HTTP_AUTHORIZATION="Bearer access-vencido")
        r = self.client.post(
            "/api/auth/logout/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.cookies[settings.REFRESH_COOKIE_NAME]["max-age"], 0)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=jti).exists())
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        self.assertEqual(self.renovar().status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/auth/logout/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            ).status_code,
            204,
        )

    def test_desactivar_revoca_todos_los_refresh_y_access(self):
        r = self.iniciar()
        refresh = r.cookies[settings.REFRESH_COOKIE_NAME].value
        access = r.data["access"]
        otro = RefreshToken.for_user(self.usuario)
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            f"/api/admin/autorizados/{self.autorizado.pk}/", {"activo": False}
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.is_active)
        self.assertEqual(
            BlacklistedToken.objects.filter(token__user=self.usuario).count(), 2
        )
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        # force_authenticate(None) borra las cookies del cliente de pruebas.
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = refresh
        self.assertEqual(self.renovar().status_code, 401)
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{self.autorizado.pk}/", {"activo": True}
            ).status_code,
            200,
        )
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=otro["jti"]).exists()
        )

    def test_refresh_revisa_lista_blanca_y_usuario_activo(self):
        for tipo in ["ausente", "usuario_inactivo"]:
            with self.subTest(tipo=tipo):
                self.usuario.cambiar_estado(EstadoCuenta.ACTIVA)
                token = RefreshToken.for_user(self.usuario)
                if tipo == "ausente":
                    self.autorizado.delete()
                else:
                    self.usuario.cambiar_estado(EstadoCuenta.DESACTIVADA)
                self.client.cookies[settings.REFRESH_COOKIE_NAME] = str(token)
                self.assertEqual(self.renovar().status_code, 401)
                self.assertTrue(
                    BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
                )
                if tipo == "ausente":
                    self.autorizado = UsuarioAutorizado.objects.create(
                        email=self.usuario.email,
                        nombre_completo="Alumno",
                        carrera=self.usuario.carrera,
                    )

    def test_probar_correo_y_error_sin_password(self):
        salida = StringIO()
        call_command("probar_correo", "destino@inacap.cl", stdout=salida)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Puerto:", salida.getvalue())
        with override_settings(EMAIL_HOST_PASSWORD="clave-sensible"):
            with patch(
                "usuarios.management.commands.probar_correo.send_mail",
                side_effect=OSError("Fallo clave-sensible"),
            ):
                with self.assertRaises(CommandError) as error:
                    call_command(
                        "probar_correo", "destino@inacap.cl", stdout=StringIO()
                    )
        self.assertIn("OSError", str(error.exception))
        self.assertNotIn("clave-sensible", str(error.exception))

    def test_checks_produccion_e_ip_confiable(self):
        from .checks import comprobar_produccion
        from tesis.views import ip_cliente
        from rest_framework.test import APIRequestFactory

        with override_settings(
            DEBUG=False,
            SECURE_COOKIES=False,
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        ):
            self.assertEqual(
                {a.id for a in comprobar_produccion(None)},
                {"usuarios.W001", "usuarios.W002"},
            )
        request = APIRequestFactory().get(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_X_NF_CLIENT_CONNECTION_IP="203.0.113.9"
        )
        self.assertEqual(ip_cliente(request), "127.0.0.1")
        request.ip_real = "203.0.113.9"
        self.assertEqual(ip_cliente(request), "203.0.113.9")
        request.ip_real = None
        self.assertEqual(ip_cliente(request), "127.0.0.1")

    def test_throttle_refresh_por_ip(self):
        for _ in range(30):
            self.assertEqual(self.renovar().status_code, 204)
        self.assertEqual(self.renovar().status_code, 429)
