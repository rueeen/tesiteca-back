from usuarios.tests_helpers import crear_usuario_activo
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from academico.models import Area, Carrera, Sede
from notificaciones.models import Notificacion
from .models import (
    Usuario,
    UsuarioAutorizado,
    SolicitudAcceso,
    EstadoCuenta,
    Rol,
    IntentoLogin,
)
from .cuentas import token_verificacion

PASS = "Biblioteca-segura-2026!"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CuentasTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.area = Area.objects.create(nombre="Informática")
        self.carrera = Carrera.objects.create(
            codigo="IEI",
            nombre="Ingeniería",
            area=self.area,
            nivel_formacion="INGENIERIA",
            duracion_semestres=8,
        )
        self.ap = Carrera.objects.create(
            codigo="AP",
            nombre="Analista",
            area=self.area,
            nivel_formacion="TECNICO",
            duracion_semestres=4,
        )
        self.sede = Sede.objects.create(nombre="Arica", ciudad="Arica", region="XV")
        self.otra = Sede.objects.create(
            nombre="Santiago", ciudad="Santiago", region="RM", orden=7
        )
        self.coord = crear_usuario_activo(
            "coord@inacap.cl",
            nombre_completo="Coordinador",
            rol=Rol.COORDINADOR,
            carrera=self.carrera,
            sede=self.sede,
        )
        self.coord_otra = crear_usuario_activo(
            "otra@inacap.cl",
            nombre_completo="Otra sede",
            rol=Rol.COORDINADOR,
            carrera=self.carrera,
            sede=self.otra,
        )
        self.director = crear_usuario_activo(
            "director@inacap.cl",
            nombre_completo="Director",
            rol=Rol.DIRECTOR,
            area=self.area,
            sede=self.sede,
        )
        self.admin = crear_usuario_activo(
            "admin@inacap.cl", nombre_completo="Admin", rol=Rol.ADMIN
        )

    def datos(self, **extra):
        return {
            "email": "nuevo@inacapmail.cl",
            "nombre_completo": "Estudiante Nuevo",
            "rut": "12.345.678-5",
            "password": PASS,
            "password2": PASS,
            "acepta_politica": True,
            "carrera": self.carrera.pk,
            "sede": self.sede.pk,
            **extra,
        }

    def registrar(self, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                "/api/auth/registro/", self.datos(**extra), format="json"
            )
        self.assertEqual(r.status_code, 201, r.data)
        return Usuario.objects.get(email=extra.get("email", "nuevo@inacapmail.cl"))

    def verificar(self, u):
        return self.client.post(
            "/api/auth/verificar-correo/", {"token": token_verificacion(u)}
        )

    def aprobar(self, u, **extra):
        self.client.force_authenticate(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(f"/api/solicitudes/{u.solicitud.pk}/aprobar/", extra)
        self.client.force_authenticate(None)
        return r

    def test_registro_correo_unico_hash_y_datos(self):
        u = self.registrar()
        self.assertEqual(u.estado_cuenta, EstadoCuenta.PENDIENTE_VERIFICACION)
        self.assertFalse(u.is_active)
        self.assertEqual(u.rut, "12345678-5")
        self.assertTrue(u.check_password(PASS))
        self.assertNotEqual(u.password, PASS)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("48 horas", mail.outbox[0].body)
        self.assertIn("Si no fuiste tú", mail.outbox[0].body)
        self.assertTrue(mail.outbox[0].alternatives)
        self.assertEqual(u.solicitud.estado, "PENDIENTE")

    def test_registro_rechaza_dominio_rol_rut_password(self):
        for cambios, campo in [
            ({"rol_solicitado": "COORDINADOR"}, "rol_solicitado"),
            ({"email": "a@gmail.com"}, "email"),
            ({"rut": "12345678-9"}, "rut"),
            ({"password": "123", "password2": "123"}, "password"),
            ({"password2": "distinta"}, "password2"),
            ({"rol_solicitado": "ADMIN"}, "rol_solicitado"),
            (
                {"email": "func@inacap.cl", "rol_solicitado": "ESTUDIANTE"},
                "rol_solicitado",
            ),
        ]:
            cache.clear()
            r = self.client.post(
                "/api/auth/registro/", self.datos(**cambios), format="json"
            )
            self.assertEqual(r.status_code, 400, r.data)
            self.assertIn(campo, r.data)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_existente_generico_y_limite_reenvio(self):
        u = self.registrar()
        for _ in range(4):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(
                    "/api/auth/reenviar-verificacion/", {"email": u.email}
                )
            self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(
            self.client.post("/api/auth/registro/", self.datos()).status_code, 201
        )
        self.assertEqual(Usuario.objects.filter(email=u.email).count(), 1)

    def test_verificacion_preaprobado_activa_y_token_unico(self):
        UsuarioAutorizado.objects.create(
            email="nuevo@inacapmail.cl",
            nombre_completo="Preaprobado",
            rol=Rol.ESTUDIANTE,
            carrera=self.carrera,
            sede=self.sede,
        )
        u = self.registrar()
        token = token_verificacion(u)
        r = self.client.post("/api/auth/verificar-correo/", {"token": token})
        self.assertEqual(r.data, {"estado": "ACTIVA"})
        u.refresh_from_db()
        self.assertTrue(u.is_active)
        self.assertEqual(u.solicitud.estado, "APROBADA")
        self.assertIsNone(u.solicitud.revisada_por)
        r = self.client.post("/api/auth/verificar-correo/", {"token": token})
        self.assertEqual(r.status_code, 400)

    def test_verificacion_pendiente_notifica_solo_sede_y_expiracion(self):
        u = self.registrar()
        r = self.verificar(u)
        self.assertEqual(r.data["estado"], "PENDIENTE_APROBACION")
        destinos = set(
            Notificacion.objects.filter(tipo="SOLICITUD_ACCESO").values_list(
                "usuario_id", flat=True
            )
        )
        self.assertEqual(destinos, {self.coord.id, self.director.id, self.admin.id})
        self.assertNotIn(self.coord_otra.id, destinos)
        u2 = self.registrar(email="segundo@inacapmail.cl", rut="11.111.111-1")
        import time

        with patch(
            "django.core.signing.time.time", return_value=time.time() - 49 * 3600
        ):
            token = token_verificacion(u2)
        self.assertEqual(
            self.client.post(
                "/api/auth/verificar-correo/", {"token": token}
            ).status_code,
            400,
        )

    def test_login_estados_no_revela_con_password_incorrecta(self):
        u = self.registrar()
        for estado, codigo in [
            (EstadoCuenta.PENDIENTE_VERIFICACION, "correo_no_verificado"),
            (EstadoCuenta.PENDIENTE_APROBACION, "pendiente_aprobacion"),
            (EstadoCuenta.RECHAZADA, "rechazada"),
            (EstadoCuenta.DESACTIVADA, "desactivada"),
        ]:
            IntentoLogin.objects.all().delete()
            u.email_verificado_en = (
                None
                if estado == EstadoCuenta.PENDIENTE_VERIFICACION
                else timezone.now()
            )
            u.save(update_fields=["email_verificado_en"])
            u.cambiar_estado(estado)
            incorrecta = self.client.post(
                "/api/auth/login/", {"email": u.email, "password": "incorrecta"}
            )
            self.assertEqual(incorrecta.status_code, 401)
            self.assertNotIn("codigo", incorrecta.data)
            r = self.client.post(
                "/api/auth/login/", {"email": u.email, "password": PASS}
            )
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.data["codigo"], codigo)
        r = self.client.post(
            "/api/auth/login/", {"email": "noexiste@inacap.cl", "password": PASS}
        )
        self.assertEqual(r.status_code, 401)

    def test_activa_login_no_envia_correo_y_bloqueo(self):
        u = self.registrar()
        self.verificar(u)
        self.assertEqual(self.aprobar(u).status_code, 200)
        antes = len(mail.outbox)
        r = self.client.post("/api/auth/login/", {"email": u.email, "password": PASS})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["usuario"]["estado_cuenta"], "ACTIVA")
        self.assertIn(settings.REFRESH_COOKIE_NAME, r.cookies)
        self.assertNotIn("refresh", r.data)
        self.assertEqual(len(mail.outbox), antes)
        for _ in range(5):
            self.client.post("/api/auth/login/", {"email": u.email, "password": "mala"})
        self.assertEqual(
            self.client.post(
                "/api/auth/login/", {"email": u.email, "password": PASS}
            ).status_code,
            429,
        )

    def test_recuperacion_un_correo_restaurar_revoca_y_unico(self):
        u = self.registrar()
        self.verificar(u)
        self.aprobar(u)
        u.refresh_from_db()
        viejo = RefreshToken.for_user(u)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(
                self.client.post(
                    "/api/auth/recuperar/", {"email": "desconocido@inacap.cl"}
                ).status_code,
                200,
            )
        self.assertEqual(len(mail.outbox), 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/auth/recuperar/", {"email": u.email})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("una hora", mail.outbox[0].body)
        token = default_token_generator.make_token(u)
        datos = {
            "uid": urlsafe_base64_encode(force_bytes(u.pk)),
            "token": token,
            "password": "Otra-password-segura-2026!",
            "password2": "Otra-password-segura-2026!",
        }
        IntentoLogin.objects.create(email=u.email, ip="127.0.0.1")
        self.assertEqual(
            self.client.post("/api/auth/restablecer/", datos).status_code, 200
        )
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=viejo["jti"]).exists()
        )
        self.assertFalse(
            IntentoLogin.objects.filter(email=u.email, exitoso=False).exists()
        )
        self.assertEqual(
            self.client.post("/api/auth/restablecer/", datos).status_code, 400
        )
        u.refresh_from_db()
        self.assertTrue(u.check_password(datos["password"]))

    def test_cambiar_password_revoca_y_emite_cookie(self):
        u = self.registrar()
        self.verificar(u)
        self.aprobar(u)
        u.refresh_from_db()
        token = RefreshToken.for_user(u)
        self.client.force_authenticate(u)
        r = self.client.post(
            "/api/auth/cambiar-password/",
            {
                "actual": PASS,
                "nueva": "Nueva-password-segura-2026!",
                "nueva2": "Nueva-password-segura-2026!",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"access"})
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
        )

    def test_solicitudes_alcance_historial_admin_modifica_carrera_y_sin_correo(self):
        u = self.registrar()
        self.verificar(u)
        self.client.force_authenticate(self.coord_otra)
        self.assertEqual(self.client.get("/api/solicitudes/").data["count"], 0)
        self.client.force_authenticate(self.coord)
        self.assertEqual(
            self.client.get("/api/solicitudes/resumen/").data["pendientes"], 1
        )
        self.assertEqual(
            self.client.post(
                f"/api/solicitudes/{u.solicitud.pk}/rechazar/", {}
            ).status_code,
            400,
        )
        antes = len(mail.outbox)
        r = self.aprobar(u, carrera=self.ap.pk)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["carrera"]["id"], self.ap.pk)
        self.assertEqual(len(mail.outbox), antes)
        u.refresh_from_db()
        self.assertEqual(u.carrera, self.ap)

    def test_director_solo_aprueba_admin_y_rechazo_reintento(self):
        u = self.registrar(email="solicitante@inacap.cl", rol_solicitado="DIRECTOR")
        self.verificar(u)
        self.client.force_authenticate(self.coord)
        self.assertEqual(
            self.client.post(f"/api/solicitudes/{u.solicitud.pk}/aprobar/").status_code,
            404,
        )
        self.client.force_authenticate(self.admin)
        antes = len(mail.outbox)
        self.assertEqual(
            self.client.post(
                f"/api/solicitudes/{u.solicitud.pk}/rechazar/",
                {"motivo": "Completar datos"},
            ).status_code,
            200,
        )
        self.assertEqual(len(mail.outbox), antes)
        self.client.force_authenticate(None)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                "/api/auth/registro/",
                self.datos(email=u.email, rol_solicitado="DIRECTOR"),
            )
        self.assertEqual(r.status_code, 201, r.data)
        u.refresh_from_db()
        self.assertEqual(u.estado_cuenta, "PENDIENTE_APROBACION")
        self.assertEqual(u.solicitud.estado, "PENDIENTE")
        self.assertEqual(len(mail.outbox), antes)

    def test_importar_preaprobado_activa_pendiente(self):
        u = self.registrar()
        self.verificar(u)
        self.client.force_authenticate(self.admin)
        contenido = f"email,rut,nombre_completo,carrera_codigo,sede\n{u.email},,Alumno,IEI,aríca\n"
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": SimpleUploadedFile("lista.csv", contenido.encode())},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["errores"], [])
        u.refresh_from_db()
        self.assertEqual(u.estado_cuenta, "ACTIVA")
        self.assertEqual(u.sede, self.sede)

    def test_crear_admin(self):
        with patch(
            "usuarios.management.commands.crear_admin.getpass", side_effect=[PASS, PASS]
        ):
            call_command(
                "crear_admin",
                "inicial@inacap.cl",
                nombre="Administrador inicial",
                sin_verificar=True,
                stdout=StringIO(),
            )
        u = Usuario.objects.get(email="inicial@inacap.cl")
        self.assertTrue(u.is_active)
        self.assertTrue(u.check_password(PASS))
        self.assertEqual(u.estado_cuenta, "ACTIVA")

    def test_regiones_niveles_admin_sedes(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(len(self.client.get("/api/catalogos/regiones/").data), 16)
        self.assertEqual(len(self.client.get("/api/catalogos/niveles/").data), 3)
        r = self.client.post(
            "/api/admin/sedes/",
            {
                "nombre": "Nueva",
                "ciudad": "Nueva",
                "region": "I",
                "orden": 2,
                "activa": True,
            },
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.client.force_authenticate(self.coord)
        self.assertEqual(
            self.client.post("/api/admin/sedes/", {"nombre": "No"}).status_code, 403
        )

    def test_importar_sedes_upsert_romanos(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sedes.csv"
            archivo.write_text(
                "nombre,ciudad,region,orden\nArica,Arica,XV,1\nTemporal,Temporal,Metropolitana de Santiago,7\n"
            )
            for _ in range(2):
                call_command("importar_sedes", str(archivo), stdout=StringIO())
        self.assertEqual(Sede.objects.filter(nombre="Temporal").count(), 1)
        self.assertEqual(Sede.objects.get(nombre="Temporal").region, "RM")

    def test_registro_throttle_cinco_por_hora(self):
        for _ in range(5):
            self.assertEqual(
                self.client.post("/api/auth/registro/", {}).status_code, 400
            )
        self.assertEqual(self.client.post("/api/auth/registro/", {}).status_code, 429)

    def test_mantenimiento_elimina_cuentas_sin_verificar_antiguas(self):
        u = self.registrar()
        Usuario.objects.filter(pk=u.pk).update(
            date_joined=timezone.now() - timedelta(days=8)
        )
        otra = self.registrar(email="reciente@inacapmail.cl", rut="11111111-1")
        with patch(
            "usuarios.management.commands.mantenimiento.tamano_ruta", return_value=0
        ):
            call_command("mantenimiento", stdout=StringIO())
        self.assertFalse(Usuario.objects.filter(pk=u.pk).exists())
        self.assertFalse(SolicitudAcceso.objects.filter(usuario_id=u.pk).exists())
        self.assertTrue(Usuario.objects.filter(pk=otra.pk).exists())

    def test_rut_unico_y_sede_obligatoria_modelo(self):
        from django.db import transaction, IntegrityError

        u = self.registrar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            crear_usuario_activo("duplicado@inacap.cl", rut=u.rut, rol=Rol.ADMIN)
        with self.assertRaises(IntegrityError), transaction.atomic():
            crear_usuario_activo(
                "sin-sede@inacap.cl", rol=Rol.COORDINADOR, carrera=self.carrera
            )

    def test_login_throttle_no_confia_ip_sin_firma(self):
        from config.throttling import ThrottleIP
        from rest_framework.test import APIRequestFactory

        req = APIRequestFactory().get(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.1"
        )
        self.assertEqual(ThrottleIP().get_ident(req), "127.0.0.1")
        req.ip_real = "203.0.113.2"
        self.assertEqual(ThrottleIP().get_ident(req), "203.0.113.2")

    def test_catalogos_registro_sin_sesion(self):
        for ruta in ["sedes", "carreras", "regiones", "niveles"]:
            r = self.client.get(f"/api/catalogos/{ruta}/")
            self.assertEqual(r.status_code, 200)
            self.assertIsInstance(r.data, list)
            self.assertGreater(len(r.data), 0)

    def extraer_enlace_texto(self, cuerpo):
        import re
        from urllib.parse import urlsplit, parse_qs

        encontrado = re.search(r"https?://\S+", cuerpo)
        self.assertIsNotNone(encontrado, cuerpo)
        enlace = encontrado.group(0)
        self.assertNotIn("&amp;", enlace)
        return urlsplit(enlace), parse_qs(urlsplit(enlace).query)

    def test_enlace_verificacion_extraido_del_correo_texto_funciona(self):
        self.registrar()
        self.assertEqual(len(mail.outbox), 1)
        url, parametros = self.extraer_enlace_texto(mail.outbox[0].body)
        self.assertEqual(url.path, "/verificar-correo")
        self.assertEqual(set(parametros), {"token"})
        r = self.client.post(
            "/api/auth/verificar-correo/", {"token": parametros["token"][0]}
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "PENDIENTE_APROBACION")

    def test_enlace_recuperacion_extraido_del_correo_texto_funciona(self):
        usuario = self.registrar()
        self.verificar(usuario)
        self.assertEqual(self.aprobar(usuario).status_code, 200)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post("/api/auth/recuperar/", {"email": usuario.email})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        url, parametros = self.extraer_enlace_texto(mail.outbox[0].body)
        self.assertEqual(url.path, "/restablecer")
        self.assertEqual(set(parametros), {"uid", "token"})
        nueva = "Otra-clave-desde-correo-2026!"
        r = self.client.post(
            "/api/auth/restablecer/",
            {
                "uid": parametros["uid"][0],
                "token": parametros["token"][0],
                "password": nueva,
                "password2": nueva,
            },
        )
        self.assertEqual(r.status_code, 200, r.data)
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(nueva))

    def test_nombre_sin_escape_en_texto_y_con_escape_en_html(self):
        from django.utils.html import escape

        nombre = "O'Higgins & Cía"
        usuario = self.registrar(nombre_completo=nombre)
        self.verificar(usuario)
        self.assertEqual(self.aprobar(usuario).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/auth/recuperar/", {"email": usuario.email})
        self.assertEqual(len(mail.outbox), 2)
        for correo in mail.outbox:
            with self.subTest(asunto=correo.subject):
                self.assertIn(nombre, correo.body)
                self.assertNotIn(str(escape(nombre)), correo.body)
                html = next(
                    contenido
                    for contenido, tipo in correo.alternatives
                    if tipo == "text/html"
                )
                self.assertIn(str(escape(nombre)), html)
                self.assertNotIn(nombre, html)
