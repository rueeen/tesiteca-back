import json
import tempfile
from datetime import timedelta
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from django.core.cache import cache
from django.core.management import call_command
from django.db import transaction
from django.test import override_settings, SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from academico.models import Area, Carrera, Sede
from usuarios.models import (
    Usuario,
    UsuarioAutorizado,
    IntentoLogin,
    SolicitudAcceso,
    EstadoCuenta,
    Rol,
)
from usuarios.tests_helpers import crear_usuario_activo
from tesis.models import (
    Tesis,
    AutorTesis,
    MaterialAdicional,
    RegistroAcceso,
    Estado,
    TipoTrabajo,
)
from tesis.tests import pdf_demo
from tesis.servicios import guardar_tesis
from notificaciones.models import Notificacion, TicketWS
from .utils import truncar_ip, enmascarar_rut, familia_user_agent
from .models import EventoPrivacidad, AceptacionPolitica
from .anonimizacion import (
    anonimizar_usuario,
    UltimoAdministrador,
    limpiar_cuentas_inactivas,
)

CLAVE = "Privacidad-segura-2026!"


class UtilidadesTests(SimpleTestCase):
    def test_ip_y_rut_y_agente(self):
        self.assertEqual(truncar_ip("200.1.2.134"), "200.1.2.0")
        self.assertEqual(truncar_ip("2001:db8:abcd:1234::1"), "2001:db8:abcd::")
        for invalida in (None, "", "inválida", "999.1.1.1"):
            self.assertEqual(truncar_ip(invalida), "")
        self.assertEqual(enmascarar_rut("12.345.678-5"), "12.***.***-5")
        self.assertEqual(enmascarar_rut("123456785"), "12.***.***-5")
        self.assertEqual(
            familia_user_agent("Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537"),
            "Chrome / Windows",
        )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PrivacidadTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)
        cambio = override_settings(PRIVATE_MEDIA_ROOT=Path(self.carpeta.name))
        cambio.enable()
        self.addCleanup(cambio.disable)
        from tesis.almacenamiento import privado

        almacenamiento = patch.dict(
            privado.__dict__,
            {"location": self.carpeta.name, "base_location": self.carpeta.name},
        )
        almacenamiento.start()
        self.addCleanup(almacenamiento.stop)
        self.sede = Sede.objects.create(nombre="Arica", ciudad="Arica")
        self.area = Area.objects.create(nombre="Informática")
        self.carrera = Carrera.objects.create(
            nombre="Informática", codigo="IEI", area=self.area
        )
        self.admin = crear_usuario_activo(
            "admin-privacidad@inacap.cl",
            CLAVE,
            nombre_completo="Administrador",
            rol=Rol.ADMIN,
        )
        self.u = self.usuario("lector-privacidad@inacapmail.cl", rut="12.345.678-5")
        self.coord = self.usuario("coord-privacidad@inacap.cl", rol=Rol.COORDINADOR)
        self.client.force_authenticate(self.u)

    def usuario(self, email, **datos):
        return crear_usuario_activo(
            email,
            CLAVE,
            nombre_completo="Nombre personal",
            carrera=self.carrera,
            area=self.area,
            sede=self.sede,
            **datos,
        )

    def datos_registro(self):
        return dict(
            email="nuevo-privacidad@inacapmail.cl",
            password=CLAVE,
            password2=CLAVE,
            nombre_completo="Nuevo",
            rut="11.111.111-1",
            carrera=self.carrera.pk,
            sede=self.sede.pk,
        )

    def trabajo(self, texto="Trabajo", publicar=True):
        datos = dict(
            titulo=texto,
            resumen="Resumen",
            tipo=TipoTrabajo.PROYECTO_TITULO,
            anio=2026,
            carrera=self.carrera,
            sede=self.sede,
            profesor_guia="Guía",
            pdf=pdf_demo(texto),
            autores=[dict(nombre_completo=self.u.nombre_completo, email=self.u.email)],
            publicar=False,
        )
        tesis = guardar_tesis(datos, self.u)
        if publicar:
            tesis.estado = Estado.PUBLICADA
            tesis.fecha_publicacion = timezone.now()
            tesis.save()
        return tesis

    def lectura(self, tesis, usuario=None, antigua=False):
        registro = RegistroAcceso.objects.create(
            usuario=usuario or self.u,
            tesis=tesis,
            accion="VER_PDF",
            ip="200.1.2.99",
            user_agent="Chrome / Windows",
        )
        if antigua:
            RegistroAcceso.objects.filter(pk=registro.pk).update(
                fecha=timezone.now() - timedelta(days=5)
            )
        return registro

    @override_settings(POLITICA_PRIVACIDAD_VERSION="version-prueba")
    def test_registro_consentimiento_me_y_nueva_version(self):
        self.client.force_authenticate(None)
        datos = self.datos_registro()
        r = self.client.post("/api/auth/registro/", datos)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Debes aceptar la política de privacidad", str(r.data))
        r = self.client.post("/api/auth/registro/", {**datos, "acepta_politica": False})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/auth/registro/", {**datos, "acepta_politica": True})
        self.assertEqual(r.status_code, 201, r.data)
        u = Usuario.objects.get(email=datos["email"])
        self.assertEqual(u.politica_aceptada_version, "version-prueba")
        self.assertIsNotNone(u.politica_aceptada_en)
        self.assertEqual(u.aceptaciones_politica.count(), 1)
        self.client.force_authenticate(self.u)
        self.assertTrue(self.client.get("/api/auth/me/").data["debe_aceptar_politica"])
        self.assertEqual(
            self.client.post("/api/cuenta/aceptar-politica/").status_code, 200
        )
        self.assertFalse(self.client.get("/api/auth/me/").data["debe_aceptar_politica"])
        with override_settings(POLITICA_PRIVACIDAD_VERSION="version-nueva"):
            self.assertTrue(
                self.client.get("/api/auth/me/").data["debe_aceptar_politica"]
            )
            self.client.post("/api/cuenta/aceptar-politica/")
        self.assertEqual(self.u.aceptaciones_politica.count(), 2)
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get("/api/salud/").data["politica_privacidad_version"],
            "version-prueba",
        )
        self.assertEqual(
            self.client.post(
                "/api/auth/login/", {"email": self.u.email, "password": CLAVE}
            ).status_code,
            200,
        )

    @override_settings(AUTORIZACION_PUBLICACION_VERSION="autorizacion-prueba")
    def test_subida_exige_autorizacion(self):
        def datos():
            return dict(
                titulo="Autorización",
                resumen="Resumen",
                tipo=TipoTrabajo.PROYECTO_INTEGRADO,
                anio=2026,
                carrera=self.carrera.pk,
                profesor_guia="Guía",
                pdf=pdf_demo("Autorización"),
                autores="[]",
            )

        r = self.client.post("/api/tesis/", datos(), format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("autoriza_publicacion", r.data)
        r = self.client.post(
            "/api/tesis/", {**datos(), "autoriza_publicacion": True}, format="multipart"
        )
        self.assertEqual(r.status_code, 201, r.data)
        tesis = Tesis.objects.get()
        self.assertTrue(tesis.autoriza_publicacion)
        self.assertEqual(tesis.autorizacion_version, "autorizacion-prueba")
        self.assertIsNotNone(tesis.autorizacion_en)

    def test_pdf_ip_completa_solo_marca_y_registro_minimo(self):
        from pypdf import PdfReader

        tesis = self.trabajo()
        r = self.client.get(
            f"/api/tesis/{tesis.pk}/pdf/",
            REMOTE_ADDR="200.1.2.99",
            HTTP_USER_AGENT="Mozilla Windows Chrome/130.0",
        )
        self.assertEqual(r.status_code, 200)
        pdf = b"".join(r.streaming_content)
        texto = " ".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("200.1.2.99", texto)
        registro = RegistroAcceso.objects.get()
        self.assertEqual(registro.ip, "200.1.2.0")
        self.assertEqual(registro.user_agent, "Chrome / Windows")

    def test_anonimizacion_conserva_publicadas_y_elimina_borradores_archivos_y_tokens(
        self,
    ):
        publicada = self.trabajo("Publicada")
        borrador = self.trabajo("Borrador", publicar=False)
        material = MaterialAdicional.objects.create(
            tesis=borrador,
            tipo="ARCHIVO",
            titulo="Adjunto",
            archivo=pdf_demo("Adjunto"),
        )
        archivos = [
            (f.storage, f.name)
            for f in [borrador.pdf_original, borrador.pdf_marcado, material.archivo]
        ]
        lectura = self.lectura(publicada)
        UsuarioAutorizado.objects.create(
            email=self.u.email,
            nombre_completo=self.u.nombre_completo,
            carrera=self.carrera,
            sede=self.sede,
        )
        IntentoLogin.objects.create(email=self.u.email, ip="200.1.2.99")
        Notificacion.objects.create(
            usuario=self.u,
            tipo="TESIS_APROBADA",
            titulo="Prueba",
            mensaje="Texto",
            enlace="/",
        )
        TicketWS.objects.create(
            usuario=self.u,
            ticket_hash="a" * 64,
            expira_en=timezone.now() + timedelta(minutes=1),
        )
        SolicitudAcceso.objects.filter(usuario=self.u).update(
            mensaje="Dato personal", motivo_rechazo="Dato personal"
        )
        token = RefreshToken.for_user(self.u)
        originales = (self.u.email, self.u.nombre_completo, self.u.rut)
        self.client.post("/api/cuenta/aceptar-politica/")
        with self.captureOnCommitCallbacks(execute=True):
            anonimizar_usuario(self.u, "solicitud_titular", self.admin)
        self.u.refresh_from_db()
        valores = json.dumps({k: str(v) for k, v in self.u.__dict__.items()})
        for original in originales:
            self.assertNotIn(original, valores)
        self.assertEqual(self.u.estado_cuenta, EstadoCuenta.ELIMINADA)
        self.assertFalse(self.u.is_active)
        self.assertFalse(self.u.has_usable_password())
        self.assertIsNone(self.u.sede)
        self.assertFalse(UsuarioAutorizado.objects.filter(email=originales[0]).exists())
        self.assertFalse(IntentoLogin.objects.filter(email=originales[0]).exists())
        self.assertFalse(self.u.notificaciones.exists())
        self.assertFalse(TicketWS.objects.filter(usuario=self.u).exists())
        self.assertFalse(self.u.aceptaciones_politica.exists())
        self.assertEqual(self.u.solicitud.mensaje, "")
        self.assertEqual(self.u.solicitud.motivo_rechazo, "")
        lectura.refresh_from_db()
        self.assertIsNone(lectura.usuario)
        self.assertEqual(lectura.ip, "200.1.2.0")
        publicada.refresh_from_db()
        autor = publicada.autores.get()
        self.assertEqual(autor.nombre_completo, originales[1])
        self.assertIsNone(autor.usuario)
        self.assertEqual(autor.email, "")
        self.assertTrue(
            publicada.pdf_original.storage.exists(publicada.pdf_original.name)
        )
        self.assertFalse(Tesis.objects.filter(pk=borrador.pk).exists())
        for storage, nombre in archivos:
            self.assertFalse(storage.exists(nombre))
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
        )
        evento = EventoPrivacidad.objects.get(tipo="anonimizacion")
        self.assertEqual(evento.usuario_id_original, self.u.pk)
        for original in originales:
            self.assertNotIn(
                original, json.dumps({k: str(v) for k, v in evento.__dict__.items()})
            )
        self.assertFalse(anonimizar_usuario(self.u, "solicitud_titular"))

    def test_ultimo_admin_y_api_solo_admin(self):
        with self.assertRaises(UltimoAdministrador):
            anonimizar_usuario(self.admin, "solicitud_titular")
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            "/api/cuenta/eliminar/", {"password": CLAVE, "confirmacion": "ELIMINAR"}
        )
        self.assertEqual(r.status_code, 409)
        self.client.force_authenticate(self.coord)
        self.assertEqual(
            self.client.post(
                f"/api/admin/usuarios/{self.u.pk}/anonimizar/",
                {"motivo": "solicitud_administrativa"},
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                f"/api/admin/usuarios/{self.u.pk}/anonimizar/",
                {"motivo": "Correo personal no debe guardarse"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/admin/usuarios/{self.u.pk}/anonimizar/",
                {"motivo": "solicitud_administrativa"},
            ).status_code,
            204,
        )

    def test_no_borra_una_tesis_publicada_que_volvio_a_revision(self):
        tesis = self.trabajo()
        tesis.estado = Estado.RECHAZADA
        tesis.fecha_publicacion = None
        tesis.save()
        anonimizar_usuario(self.u, "solicitud_titular")
        self.assertTrue(Tesis.objects.filter(pk=tesis.pk).exists())

    def test_rollback_no_borra_archivos_ni_deja_cuenta_a_medias(self):
        tesis = self.trabajo(publicar=False)
        with patch(
            "privacidad.anonimizacion.EventoPrivacidad.objects.create",
            side_effect=RuntimeError("Fallo"),
        ):
            with self.assertRaises(RuntimeError):
                anonimizar_usuario(self.u, "solicitud_titular")
        self.u.refresh_from_db()
        self.assertEqual(self.u.estado_cuenta, EstadoCuenta.ACTIVA)
        self.assertTrue(Tesis.objects.filter(pk=tesis.pk).exists())
        self.assertTrue(tesis.pdf_original.storage.exists(tesis.pdf_original.name))

    @override_settings(
        RETENCION_LECTURAS_DIAS=1, RETENCION_SOLICITUDES_RECHAZADAS_DIAS=1
    )
    def test_retencion_simulacion_y_rechazadas_antiguas(self):
        tesis = self.trabajo()
        antigua = self.lectura(tesis, antigua=True)
        reciente = self.lectura(tesis)
        SolicitudAcceso.objects.filter(usuario=self.coord).update(
            estado="RECHAZADA", revisada_en=timezone.now() - timedelta(days=5)
        )
        self.coord.cambiar_estado(EstadoCuenta.RECHAZADA)
        salida = StringIO()
        call_command("anonimizar", dry_run=True, stdout=salida)
        self.assertIn("lecturas=1; rechazadas=1; inactivas=0", salida.getvalue())
        antigua.refresh_from_db()
        self.assertEqual(antigua.usuario_id, self.u.pk)
        self.coord.refresh_from_db()
        self.assertEqual(self.coord.estado_cuenta, EstadoCuenta.RECHAZADA)
        call_command("anonimizar", stdout=StringIO())
        antigua.refresh_from_db()
        reciente.refresh_from_db()
        self.coord.refresh_from_db()
        self.assertIsNone(antigua.usuario_id)
        self.assertEqual(antigua.user_agent, "")
        self.assertEqual(reciente.usuario_id, self.u.pk)
        self.assertEqual(self.coord.estado_cuenta, EstadoCuenta.ELIMINADA)
        self.assertEqual(limpiar_cuentas_inactivas(0), 0)

    def test_retencion_inactivas_excluye_admin_y_login_nulo(self):
        antigua = timezone.now() - timedelta(days=10)
        Usuario.objects.filter(pk__in=[self.admin.pk, self.u.pk]).update(
            last_login=antigua
        )
        self.assertEqual(limpiar_cuentas_inactivas(1), 1)
        self.admin.refresh_from_db()
        self.coord.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.coord.is_active)

    def test_exportacion_solo_datos_propios_sin_hash_y_throttle(self):
        tesis = self.trabajo()
        self.lectura(tesis)
        self.lectura(tesis, usuario=self.coord)
        self.client.post("/api/cuenta/aceptar-politica/")
        r = self.client.get("/api/cuenta/mis-datos/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r["Content-Disposition"], 'attachment; filename="mis-datos-tesiteca.json"'
        )
        self.assertEqual(len(r.data["lecturas"]), 1)
        self.assertEqual(len(r.data["tesis_subidas"]), 1)
        self.assertEqual(len(r.data["autorias"]), 1)
        self.assertEqual(len(r.data["aceptaciones_politica"]), 1)
        self.assertNotIn(self.u.password, json.dumps(r.data, default=str))
        self.assertNotIn(self.coord.email, json.dumps(r.data, default=str))
        for _ in range(4):
            self.assertEqual(self.client.get("/api/cuenta/mis-datos/").status_code, 200)
        self.assertEqual(self.client.get("/api/cuenta/mis-datos/").status_code, 429)

    def test_rectificacion_y_eliminar_con_password(self):
        self.assertEqual(
            self.client.patch("/api/cuenta/perfil/", {"rut": "otro"}).status_code, 400
        )
        self.assertEqual(
            self.client.patch(
                "/api/cuenta/perfil/", {"nombre_completo": "Nombre rectificado"}
            ).status_code,
            200,
        )
        email = self.u.email
        datos = {"password": "incorrecta", "confirmacion": "ELIMINAR"}
        self.assertEqual(
            self.client.post("/api/cuenta/eliminar/", datos).status_code, 400
        )
        datos["password"] = CLAVE
        r = self.client.post("/api/cuenta/eliminar/", datos)
        self.assertEqual(r.status_code, 204)
        from django.conf import settings

        self.assertEqual(r.cookies[settings.REFRESH_COOKIE_NAME]["max-age"], 0)
        self.u.refresh_from_db()
        self.assertEqual(self.u.estado_cuenta, EstadoCuenta.ELIMINADA)
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(
                "/api/auth/login/", {"email": email, "password": CLAVE}
            ).status_code,
            401,
        )

    def test_rut_listado_enmascarado_detalle_auditado_y_ambito(self):
        self.client.force_authenticate(self.coord)
        r = self.client.get("/api/solicitudes/")
        self.assertEqual(r.data["results"][0]["usuario"]["rut"], "12.***.***-5")
        solicitud = self.u.solicitud
        r = self.client.get(f"/api/solicitudes/{solicitud.pk}/")
        self.assertEqual(r.data["usuario"]["rut"], self.u.rut)
        evento = EventoPrivacidad.objects.get(tipo="ver_rut")
        self.assertEqual(evento.ejecutado_por, self.coord)
        self.assertNotIn(self.u.rut, evento.motivo)
        otra_sede = Sede.objects.create(nombre="Otra", ciudad="Otra")
        SolicitudAcceso.objects.filter(pk=solicitud.pk).update(sede=otra_sede)
        self.assertEqual(
            self.client.get(f"/api/solicitudes/{solicitud.pk}/").status_code, 404
        )
        self.assertEqual(EventoPrivacidad.objects.filter(tipo="ver_rut").count(), 1)
        autorizado = UsuarioAutorizado.objects.create(
            email="preaprobado@inacapmail.cl",
            nombre_completo="Prueba",
            rut=self.u.rut,
            carrera=self.carrera,
            sede=self.sede,
        )
        r = self.client.get("/api/admin/autorizados/")
        self.assertEqual(r.data["results"][0]["rut"], "12.***.***-5")
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.get("/api/admin/autorizados/").data["results"][0]["rut"],
            self.u.rut,
        )
