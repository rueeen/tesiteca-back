from io import StringIO
from unittest.mock import patch
from django.conf import settings
from django.contrib import admin
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from usuarios.tests_helpers import crear_usuario_activo
from usuarios.models import (
    Usuario,
    UsuarioAutorizado,
    SolicitudAcceso,
    EstadoCuenta,
    Rol,
)
from usuarios.cuentas import token_verificacion
from academico.models import Area, Carrera, Sede

CLAVE = "Clave-valida-de-prueba-2026!"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReglaCuentasTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.sede = Sede.objects.create(nombre="Arica", ciudad="Arica")
        area = Area.objects.create(nombre="Informática")
        self.carrera = Carrera.objects.create(
            nombre="Informática", codigo="IEI", area=area
        )
        self.admin = crear_usuario_activo(
            "admin@inacap.cl",
            CLAVE,
            nombre_completo="Administrador",
            rol=Rol.ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def pendiente(self, email="pendiente@inacapmail.cl"):
        usuario = Usuario.objects.create_user(
            email,
            CLAVE,
            nombre_completo="Pendiente",
            carrera=self.carrera,
            sede=self.sede,
        )
        SolicitudAcceso.objects.create(
            usuario=usuario,
            rol_solicitado=Rol.ESTUDIANTE,
            carrera=self.carrera,
            sede=self.sede,
        )
        return usuario

    def aprobar(self, u):
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/solicitudes/{u.solicitud.pk}/aprobar/")
        self.client.force_authenticate(None)
        return r

    def verificar(self, u):
        return self.client.post(
            "/api/auth/verificar-correo/", {"token": token_verificacion(u)}
        )

    def test_invariante_python_y_constraint(self):
        with self.assertRaises(ValidationError):
            Usuario.objects.create_user(
                "sin-aprobacion@inacap.cl",
                CLAVE,
                rol=Rol.ADMIN,
                estado_cuenta=EstadoCuenta.ACTIVA,
                email_verificado_en=timezone.now(),
            )
        u = self.pendiente()
        with self.assertRaises(ValidationError):
            u.cambiar_estado(EstadoCuenta.ACTIVA)
        u.estado_cuenta = EstadoCuenta.ACTIVA
        with self.assertRaises(ValidationError):
            u.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.filter(pk=u.pk).update(estado_cuenta="ACTIVA")
        u.estado_cuenta = EstadoCuenta.PENDIENTE_VERIFICACION
        u.email_verificado_en = timezone.now()
        u.save()
        with self.assertRaises(ValidationError):
            u.cambiar_estado(EstadoCuenta.ACTIVA)

    def test_aprobar_antes_de_validar(self):
        u = self.pendiente()
        r = self.aprobar(u)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado_cuenta"], "PENDIENTE_VERIFICACION")
        self.assertFalse(r.data["correo_validado"])
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        self.assertEqual(u.solicitud.estado, "APROBADA")
        r = self.client.post("/api/auth/login/", {"email": u.email, "password": CLAVE})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["codigo"], "correo_no_verificado")
        self.assertEqual(self.verificar(u).data["estado"], "ACTIVA")
        self.assertEqual(
            self.client.post(
                "/api/auth/login/", {"email": u.email, "password": CLAVE}
            ).status_code,
            200,
        )
        self.client.force_authenticate(self.admin)
        historial = self.client.get("/api/solicitudes/?estado=APROBADA").data["results"]
        item = next(x for x in historial if x["usuario"]["id"] == u.pk)
        self.assertTrue(item["correo_validado"])

    def test_validar_antes_de_aprobar(self):
        u = self.pendiente()
        self.assertEqual(self.verificar(u).data["estado"], "PENDIENTE_APROBACION")
        r = self.aprobar(u)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado_cuenta"], "ACTIVA")
        self.assertTrue(
            UsuarioAutorizado.objects.filter(email=u.email, activo=True).exists()
        )

    def test_lista_blanca_opcional(self):
        for numero, habilitada in enumerate([True, False]):
            with (
                self.subTest(habilitada=habilitada),
                override_settings(PREAPROBACION_LISTA_BLANCA=habilitada),
            ):
                u = self.pendiente(f"blanca{numero}@inacapmail.cl")
                UsuarioAutorizado.objects.create(
                    email=u.email,
                    nombre_completo=u.nombre_completo,
                    carrera=self.carrera,
                    sede=self.sede,
                )
                u.refresh_from_db()
                self.assertFalse(u.is_active)
                self.assertEqual(
                    self.verificar(u).data["estado"],
                    "ACTIVA" if habilitada else "PENDIENTE_APROBACION",
                )

    def test_crear_admin_exige_enlace_y_emergencia(self):
        with patch(
            "usuarios.management.commands.crear_admin.getpass",
            side_effect=[CLAVE, CLAVE],
        ):
            with self.captureOnCommitCallbacks(execute=True):
                salida = StringIO()
                call_command(
                    "crear_admin",
                    "nuevo-admin@inacap.cl",
                    nombre="Administrador nuevo",
                    stdout=salida,
                )
        u = Usuario.objects.get(email="nuevo-admin@inacap.cl")
        self.assertEqual(u.estado_cuenta, "PENDIENTE_VERIFICACION")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Revisa tu correo", salida.getvalue())
        self.assertEqual(u.solicitud.mensaje, "Creado por consola")
        r = self.client.post("/api/auth/login/", {"email": u.email, "password": CLAVE})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["codigo"], "correo_no_verificado")
        self.assertEqual(self.verificar(u).data["estado"], "ACTIVA")
        self.assertEqual(
            self.client.post(
                "/api/auth/login/", {"email": u.email, "password": CLAVE}
            ).status_code,
            200,
        )
        mail.outbox.clear()
        with patch(
            "usuarios.management.commands.crear_admin.getpass",
            side_effect=[CLAVE, CLAVE],
        ):
            with self.captureOnCommitCallbacks(execute=True):
                salida = StringIO()
                call_command(
                    "crear_admin",
                    "emergencia@inacap.cl",
                    nombre="Admin emergencia",
                    sin_verificar=True,
                    stdout=salida,
                )
        emergencia = Usuario.objects.get(email="emergencia@inacap.cl")
        self.assertEqual(emergencia.estado_cuenta, "ACTIVA")
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("ADVERTENCIA", salida.getvalue())
        sello = emergencia.email_verificado_en
        with patch(
            "usuarios.management.commands.crear_admin.getpass",
            side_effect=[CLAVE, CLAVE],
        ):
            call_command(
                "crear_admin",
                emergencia.email,
                nombre="Nombre actualizado",
                stdout=StringIO(),
            )
        emergencia.refresh_from_db()
        self.assertEqual(emergencia.email_verificado_en, sello)
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_form_crea_aprobada_pendiente_y_no_permite_activar(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                "/admin/usuarios/usuario/add/",
                {
                    "email": "panel@inacap.cl",
                    "nombre_completo": "Usuario panel",
                    "rol": "COORDINADOR",
                    "carrera": self.carrera.pk,
                    "sede": self.sede.pk,
                    "password1": CLAVE,
                    "password2": CLAVE,
                    "_save": "Guardar",
                },
            )
        self.assertEqual(r.status_code, 302, getattr(r, "context_data", None))
        u = Usuario.objects.get(email="panel@inacap.cl")
        self.assertEqual(u.estado_cuenta, "PENDIENTE_VERIFICACION")
        self.assertFalse(u.is_active)
        self.assertEqual(u.solicitud.estado, "APROBADA")
        self.assertEqual(u.solicitud.revisada_por, self.admin)
        self.assertEqual(len(mail.outbox), 1)
        datos = {
            "email": u.email,
            "nombre_completo": u.nombre_completo,
            "rol": u.rol,
            "carrera": self.carrera.pk,
            "sede": self.sede.pk,
            "estado_cuenta": "ACTIVA",
            "_save": "Guardar",
        }
        r = self.client.post(f"/admin/usuarios/usuario/{u.pk}/change/", datos)
        self.assertEqual(r.status_code, 200)
        self.assertIn("estado_cuenta", r.context["adminform"].form.errors)

    def test_sesion_sin_autorizado_y_mantenimiento_sincroniza(self):
        self.assertFalse(
            UsuarioAutorizado.objects.filter(email=self.admin.email).exists()
        )
        r = self.client.post(
            "/api/auth/login/", {"email": self.admin.email, "password": CLAVE}
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            ).status_code,
            200,
        )
        with patch(
            "usuarios.management.commands.mantenimiento.tamano_ruta", return_value=0
        ):
            salida = StringIO()
            call_command("mantenimiento", stdout=salida)
        self.assertIn("Autorizados faltantes creados: 1", salida.getvalue())
        autorizado = UsuarioAutorizado.objects.get(email=self.admin.email)
        autorizado.activo = False
        autorizado.save()
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            ).status_code,
            401,
        )

    def test_cambiar_password_exige_misma_regla(self):
        u = self.pendiente()
        self.client.force_authenticate(u)
        r = self.client.post(
            "/api/auth/cambiar-password/",
            {
                "actual": CLAVE,
                "nueva": "Otra-password-correcta-2026!",
                "nueva2": "Otra-password-correcta-2026!",
            },
        )
        self.assertEqual(r.status_code, 403)

    def test_migracion_no_sobrescribe_decisiones_previas(self):
        import importlib
        from django.apps import apps

        SolicitudAcceso.objects.filter(usuario=self.admin).update(
            estado="RECHAZADA", motivo_rechazo="Decisión existente"
        )
        migracion = importlib.import_module(
            "usuarios.migrations.0004_alter_solicitudacceso_sede_and_more"
        )
        with self.assertRaises(RuntimeError):
            migracion.aprobar_legadas(apps, None)
        solicitud = SolicitudAcceso.objects.get(usuario=self.admin)
        self.assertEqual(solicitud.estado, "RECHAZADA")
        self.assertEqual(solicitud.motivo_rechazo, "Decisión existente")
