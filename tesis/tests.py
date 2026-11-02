import json
import shutil
import tempfile
from io import BytesIO
from unittest.mock import patch
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.core import mail
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from datetime import timedelta
from openpyxl import Workbook
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from rest_framework.test import APITestCase
from academico.models import Area, Carrera, Sede
from usuarios.models import Usuario, UsuarioAutorizado, Rol, CodigoAcceso
from .models import Tesis, Estado, MaterialAdicional, RegistroAcceso
from .servicios import guardar_tesis
from .marca_agua import aplicar_marca_lector
from .serializers import MaterialSerializer
from .almacenamiento import privado


def pdf_demo(texto="Documento de prueba", rotado=False):
    salida = BytesIO()
    c = canvas.Canvas(salida, pagesize=(450, 700))
    for i in range(2):
        c.drawString(40, 500, f"{texto} página {i}")
        c.showPage()
    c.save()
    if rotado:
        lector = PdfReader(BytesIO(salida.getvalue()))
        escritor = PdfWriter()
        for pagina in lector.pages:
            escritor.add_page(pagina.rotate(90))
        salida = BytesIO()
        escritor.write(salida)
    return SimpleUploadedFile(
        "prueba.pdf", salida.getvalue(), content_type="application/pdf"
    )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication"
        ],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_PAGINATION_CLASS": "config.paginacion.Paginacion",
        "PAGE_SIZE": 12,
        "DEFAULT_FILTER_BACKENDS": [
            "django_filters.rest_framework.DjangoFilterBackend",
            "rest_framework.filters.OrderingFilter",
        ],
        "DEFAULT_THROTTLE_RATES": {"codigo": "1000/min"},
    },
)
class BackendTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.directorio = tempfile.mkdtemp()
        self.anterior = privado.location
        privado.__dict__["location"] = self.directorio
        privado.__dict__["base_location"] = self.directorio
        self.addCleanup(self.limpiar)
        self.sede = Sede.objects.create(nombre="Arica", ciudad="Arica")
        self.area = Area.objects.create(nombre="Informática")
        self.otra_area = Area.objects.create(nombre="Salud")
        self.iei = Carrera.objects.create(
            nombre="Ingeniería", codigo="IEI", area=self.area, permite_repositorio=True
        )
        self.ap = Carrera.objects.create(
            nombre="Analista", codigo="AP", area=self.area, permite_repositorio=True
        )
        self.otra = Carrera.objects.create(
            nombre="Enfermería", codigo="ENF", area=self.otra_area
        )
        self.admin = Usuario.objects.create_user(
            "admin@inacap.cl", nombre_completo="Admin", rol=Rol.ADMIN, sede=self.sede
        )
        self.alumno = Usuario.objects.create_user(
            "alumno@inacapmail.cl",
            nombre_completo="Alumno AP",
            carrera=self.ap,
            sede=self.sede,
        )
        self.otro = Usuario.objects.create_user(
            "otro@inacapmail.cl",
            nombre_completo="Alumno IEI",
            carrera=self.iei,
            sede=self.sede,
        )
        self.coordinador = Usuario.objects.create_user(
            "coord@inacap.cl",
            nombre_completo="Coordinador",
            rol=Rol.COORDINADOR,
            carrera=self.ap,
            sede=self.sede,
        )
        self.director = Usuario.objects.create_user(
            "dir@inacap.cl",
            nombre_completo="Director",
            rol=Rol.DIRECTOR,
            area=self.area,
            sede=self.sede,
        )

    def limpiar(self):
        privado.__dict__["location"] = self.anterior
        privado.__dict__["base_location"] = self.anterior
        shutil.rmtree(self.directorio)

    def login(self, usuario):
        self.client.force_authenticate(usuario)

    def tesis(
        self, carrera=None, usuario=None, titulo="Tesis", publicar=True, pdf=None
    ):
        return guardar_tesis(
            {
                "titulo": titulo,
                "resumen": "Resumen",
                "palabras_clave": "redes,software",
                "tipo": "TESIS",
                "anio": 2025,
                "carrera": carrera or self.ap,
                "sede": self.sede,
                "profesor_guia": "Guía",
                "pdf": pdf or pdf_demo(titulo),
                "autores": [],
                "publicar": publicar,
            },
            usuario or self.admin,
        )

    def autorizar(self, usuario):
        return UsuarioAutorizado.objects.create(
            email=usuario.email,
            nombre_completo=usuario.nombre_completo,
            rol=usuario.rol,
            carrera=usuario.carrera,
            sede=self.sede,
            area=usuario.area,
        )

    def codigo(self, usuario, codigo="123456"):
        return CodigoAcceso.objects.create(
            email=usuario.email,
            codigo_hash=make_password(codigo),
            expira_en=timezone.now() + timedelta(minutes=10),
        )

    def test_no_autorizado_no_recibe_correo_y_respuesta_generica(self):
        r = self.client.post(
            "/api/auth/solicitar-codigo/", {"email": "ausente@inacap.cl"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(CodigoAcceso.objects.filter(usado=False).exists())

    def test_dominio_rechazado(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/solicitar-codigo/", {"email": "alumno@gmail.com"}
            ).status_code,
            400,
        )

    def test_codigo_correcto_jwt_normalizacion_y_reuso(self):
        self.autorizar(self.alumno)
        with patch("usuarios.views.secrets.randbelow", return_value=123456):
            r = self.client.post(
                "/api/auth/solicitar-codigo/", {"email": self.alumno.email.upper()}
            )
        self.assertEqual(r.status_code, 200)
        self.assertIn("123456", mail.outbox[0].body)
        self.assertNotEqual(CodigoAcceso.objects.get().codigo_hash, "123456")
        r = self.client.post(
            "/api/auth/verificar-codigo/",
            {"email": self.alumno.email, "codigo": "123456"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        token = r.data["access"]
        refresh = r.data["refresh"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/auth/me/").data["rol"], Rol.ESTUDIANTE)
        self.client.credentials()
        self.assertEqual(
            self.client.post("/api/auth/refresh/", {"refresh": refresh}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/auth/verificar-codigo/",
                {"email": self.alumno.email, "codigo": "123456"},
            ).status_code,
            400,
        )

    def test_cinco_intentos_y_expiracion(self):
        self.autorizar(self.alumno)
        codigo = self.codigo(self.alumno)
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    "/api/auth/verificar-codigo/",
                    {"email": self.alumno.email, "codigo": "000000"},
                ).status_code,
                400,
            )
        codigo.refresh_from_db()
        self.assertTrue(codigo.usado)
        self.assertEqual(codigo.intentos, 5)
        self.assertEqual(
            self.client.post(
                "/api/auth/verificar-codigo/",
                {"email": self.alumno.email, "codigo": "123456"},
            ).status_code,
            400,
        )
        codigo = self.codigo(self.alumno)
        codigo.expira_en = timezone.now() - timedelta(seconds=1)
        codigo.save()
        self.assertEqual(
            self.client.post(
                "/api/auth/verificar-codigo/",
                {"email": self.alumno.email, "codigo": "123456"},
            ).status_code,
            400,
        )

    def test_limite_email_e_invalida_codigo_previo(self):
        self.autorizar(self.alumno)
        for _ in range(3):
            self.assertEqual(
                self.client.post(
                    "/api/auth/solicitar-codigo/", {"email": self.alumno.email}
                ).status_code,
                200,
            )
        self.assertEqual(CodigoAcceso.objects.filter(usado=False).count(), 1)
        self.assertEqual(
            self.client.post(
                "/api/auth/solicitar-codigo/", {"email": self.alumno.email}
            ).status_code,
            429,
        )

    def test_desactivado_no_login(self):
        autorizado = self.autorizar(self.alumno)
        self.codigo(self.alumno)
        autorizado.activo = False
        autorizado.save()
        self.assertEqual(
            self.client.post(
                "/api/auth/verificar-codigo/",
                {"email": self.alumno.email, "codigo": "123456"},
            ).status_code,
            400,
        )

    def excel(self, filas):
        libro = Workbook()
        libro.active.append(
            ["email", "rut", "nombre_completo", "rol", "carrera_codigo", "area", "sede"]
        )
        for fila in filas:
            libro.active.append(fila)
        salida = BytesIO()
        libro.save(salida)
        return SimpleUploadedFile("lista.xlsx", salida.getvalue())

    def test_importacion_excel_upsert_errores(self):
        self.login(self.admin)
        filas = [
            ["nuevo@inacapmail.cl", "1", "Nuevo", "ESTUDIANTE", "AP", "", "Arica"],
            ["malo@gmail.com", "", "Malo", "ESTUDIANTE", "AP", "", "Arica"],
            ["sin@inacap.cl", "", "Sin carrera", "ESTUDIANTE", "", "", "Arica"],
        ]
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": self.excel(filas)},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(
            (r.data["total_filas"], r.data["creados"], len(r.data["errores"])),
            (3, 1, 2),
        )
        filas[0][2] = "Actualizado"
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": self.excel(filas[:1])},
            format="multipart",
        )
        self.assertEqual(r.data["actualizados"], 1)
        self.assertEqual(UsuarioAutorizado.objects.get().nombre_completo, "Actualizado")
        self.assertEqual(
            self.client.get("/api/admin/autorizados/plantilla/").status_code, 200
        )

    def test_importacion_ambito_y_patch_no_escalan_rol(self):
        self.login(self.coordinador)
        filas = [
            ["ap@inacapmail.cl", "", "AP", "ESTUDIANTE", "AP", "", "Arica"],
            ["iei@inacapmail.cl", "", "IEI", "ESTUDIANTE", "IEI", "", "Arica"],
            ["admin@inacap.cl", "", "Admin", "ADMIN", "", "", "Arica"],
        ]
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": self.excel(filas)},
            format="multipart",
        )
        self.assertEqual(r.data["creados"], 1)
        self.assertEqual(len(r.data["errores"]), 2)
        pk = UsuarioAutorizado.objects.get().pk
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{pk}/", {"rol": "ADMIN"}
            ).status_code,
            403,
        )

    def test_visibilidad_biblioteca_pendientes_y_propias(self):
        ap = self.tesis()
        iei = self.tesis(self.iei, titulo="IEI")
        pendiente = self.tesis(titulo="Pendiente", publicar=False)
        propia = self.tesis(usuario=self.alumno, titulo="Propia", publicar=False)
        self.login(self.alumno)
        r = self.client.get("/api/tesis/")
        self.assertEqual([x["id"] for x in r.data["results"]], [ap.pk])
        self.assertEqual(self.client.get(f"/api/tesis/{iei.pk}/").status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/tesis/{pendiente.pk}/").status_code, 404
        )
        self.assertEqual(self.client.get(f"/api/tesis/{propia.pk}/").status_code, 200)
        self.assertEqual(self.client.get("/api/tesis/mis-tesis/").data["count"], 1)
        self.assertEqual(self.client.get("/api/tesis/pendientes/").status_code, 403)
        self.login(self.coordinador)
        self.assertEqual(self.client.get("/api/tesis/pendientes/").data["count"], 2)

    def test_material_restringido_sin_url_y_acceso_denegado(self):
        tesis = self.tesis(self.iei)
        material = MaterialAdicional.objects.create(
            tesis=tesis,
            tipo="REPOSITORIO",
            titulo="Código",
            url="https://github.com/demo/demo",
        )
        # Un autor de otra carrera puede ver su propia tesis, sin adquirir acceso al repositorio.
        tesis.autores.create(nombre_completo="Autor AP", usuario=self.alumno)
        self.login(self.alumno)
        r = self.client.get(f"/api/tesis/{tesis.pk}/")
        dato = r.data["materiales"][0]
        self.assertTrue(dato["restringido"])
        self.assertNotIn("url", dato)
        self.assertEqual(
            self.client.post(f"/api/materiales/{material.pk}/acceso/").status_code, 403
        )
        self.login(self.director)
        self.assertEqual(
            self.client.post(f"/api/materiales/{material.pk}/acceso/").data["url"],
            material.url,
        )

    def test_marca_fija_y_dinamica_paginas_rotadas(self):
        tesis = self.tesis(pdf=pdf_demo(rotado=True))
        with tesis.pdf_marcado.open("rb") as archivo:
            lector = PdfReader(archivo)
            self.assertEqual(len(lector.pages), 2)
            for p in lector.pages:
                self.assertIn("INACAP", p.extract_text())
                self.assertIn("Biblioteca de Tesis", p.extract_text())
            self.assertEqual(
                (
                    float(lector.pages[0].mediabox.width),
                    float(lector.pages[0].mediabox.height),
                ),
                (700, 450),
            )
        self.login(self.alumno)
        r = self.client.get(f"/api/tesis/{tesis.pk}/pdf/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertTrue(r["Content-Disposition"].startswith("inline"))
        lector = PdfReader(BytesIO(b"".join(r.streaming_content)))
        self.assertIn(self.alumno.email, lector.pages[0].extract_text())
        self.assertEqual(RegistroAcceso.objects.count(), 1)

    def test_encriptado_duplicado_e_invalido_rechazados(self):
        archivo = pdf_demo("Duplicado")
        contenido = archivo.read()
        archivo.seek(0)
        self.tesis(pdf=archivo)
        from rest_framework.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, "Este PDF ya fue subido"):
            self.tesis(
                pdf=SimpleUploadedFile("duplicado.pdf", contenido), titulo="Otro"
            )
        escritor = PdfWriter()
        escritor.add_blank_page(width=300, height=400)
        escritor.encrypt("clave")
        salida = BytesIO()
        escritor.write(salida)
        with self.assertRaisesMessage(ValidationError, "encriptados"):
            self.tesis(pdf=SimpleUploadedFile("enc.pdf", salida.getvalue()))
        with self.assertRaises(ValidationError):
            self.tesis(pdf=SimpleUploadedFile("falso.pdf", b"no pdf"))

    def test_sin_token_pdf_401_y_archivos_no_publicos(self):
        tesis = self.tesis()
        self.assertEqual(
            self.client.get(f"/api/tesis/{tesis.pk}/pdf/").status_code, 401
        )
        self.assertEqual(
            self.client.get("/private_media/" + tesis.pdf_original.name).status_code,
            404,
        )
        self.login(self.alumno)
        self.assertEqual(
            self.client.get(f"/api/tesis/{tesis.pk}/pdf-original/").status_code, 403
        )
        self.assertNotIn(
            "pdf_original", self.client.get(f"/api/tesis/{tesis.pk}/").data
        )

    def test_subida_estudiante_revision_autor_y_carrera(self):
        self.login(self.alumno)
        datos = {
            "titulo": "Subida",
            "resumen": "Texto",
            "tipo": "TESIS",
            "anio": 2026,
            "carrera": self.ap.pk,
            "sede": self.sede.pk,
            "profesor_guia": "Guía",
            "autores": json.dumps([]),
            "pdf": pdf_demo("Subida"),
            "publicar": "true",
        }
        r = self.client.post("/api/tesis/", datos, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado"], Estado.EN_REVISION)
        tesis = Tesis.objects.get()
        self.assertTrue(tesis.autores.filter(usuario=self.alumno).exists())
        self.assertEqual(
            self.client.patch(f"/api/tesis/{tesis.pk}/", {"titulo": "No"}).status_code,
            403,
        )
        datos["pdf"] = pdf_demo("Fuera")
        datos["carrera"] = self.iei.pk
        self.assertEqual(
            self.client.post("/api/tesis/", datos, format="multipart").status_code, 400
        )

    def test_revision_rechazo_edicion_reemplazo_reenvio_aprobacion(self):
        tesis = self.tesis(usuario=self.alumno, publicar=False)
        self.login(self.coordinador)
        self.assertEqual(
            self.client.post(
                f"/api/tesis/{tesis.pk}/rechazar/", {"observacion": ""}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/tesis/{tesis.pk}/rechazar/", {"observacion": "Corregir"}
            ).status_code,
            200,
        )
        self.login(self.alumno)
        original = tesis.hash_sha256
        r = self.client.patch(
            f"/api/tesis/{tesis.pk}/",
            {"pdf": pdf_demo("Reemplazo")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        tesis.refresh_from_db()
        self.assertNotEqual(tesis.hash_sha256, original)
        self.assertEqual(
            self.client.post(f"/api/tesis/{tesis.pk}/reenviar/").status_code, 200
        )
        self.login(self.coordinador)
        self.assertEqual(
            self.client.post(f"/api/tesis/{tesis.pk}/aprobar/").status_code, 200
        )
        tesis.refresh_from_db()
        self.assertEqual(tesis.estado, Estado.PUBLICADA)
        self.assertEqual(tesis.revisado_por, self.coordinador)

    def test_fallo_marca_revierte_db_y_archivos(self):
        from pathlib import Path

        with patch(
            "tesis.servicios.generar_marca_fija", side_effect=RuntimeError("Fallo")
        ):
            with self.assertRaises(RuntimeError):
                self.tesis()
        self.assertEqual(Tesis.objects.count(), 0)
        self.assertFalse(any(p.is_file() for p in Path(self.directorio).rglob("*")))

    def test_busqueda_contenido_filtros_y_paginacion(self):
        tesis = self.tesis(pdf=pdf_demo("Contenido secreto buscable"))
        self.login(self.alumno)
        self.assertEqual(self.client.get("/api/tesis/?search=secreto").data["count"], 0)
        self.assertEqual(
            self.client.get("/api/tesis/?search=secreto&en_contenido=true").data[
                "count"
            ],
            1,
        )
        self.assertEqual(
            self.client.get("/api/tesis/?anio_desde=2026").data["count"], 0
        )
        r = self.client.get(
            "/api/tesis/?page_size=48&palabra_clave=redes&ordering=titulo"
        )
        self.assertEqual(r.data["count"], 1)
        self.assertNotIn("texto_extraido", r.data["results"][0])

    def test_material_archivo_limites_y_descarga(self):
        tesis = self.tesis()
        self.login(self.admin)
        r = self.client.post(
            f"/api/tesis/{tesis.pk}/materiales/",
            {"tipo": "ARCHIVO", "titulo": "Adjunto", "archivo": pdf_demo("Adjunto")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotIn("archivo", r.data)
        r = self.client.get(f"/api/materiales/{r.data['id']}/descargar/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))
        self.assertEqual(RegistroAcceso.objects.get().accion, "DESCARGAR_MATERIAL")
        r = self.client.post(
            f"/api/tesis/{tesis.pk}/materiales/",
            {
                "tipo": "ARCHIVO",
                "titulo": "Malo",
                "archivo": SimpleUploadedFile("mal.exe", b"abc"),
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)

    def test_director_ambito_y_autorizados(self):
        self.login(self.director)
        filas = [
            ["ap@inacap.cl", "", "AP", "COORDINADOR", "AP", "", "Arica"],
            ["enf@inacap.cl", "", "ENF", "ESTUDIANTE", "ENF", "", "Arica"],
        ]
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": self.excel(filas)},
            format="multipart",
        )
        self.assertEqual(r.data["creados"], 1)
        self.assertEqual(len(r.data["errores"]), 1)
        tesis = self.tesis(self.otra, publicar=False)
        self.assertEqual(
            self.client.post(f"/api/tesis/{tesis.pk}/aprobar/").status_code, 404
        )

    def test_error_smtp_conserva_respuesta_generica(self):
        self.autorizar(self.alumno)
        with patch(
            "usuarios.views.send_mail", side_effect=OSError("SMTP no disponible")
        ):
            with self.assertLogs("usuarios.views", level="ERROR"):
                r = self.client.post(
                    "/api/auth/solicitar-codigo/", {"email": self.alumno.email}
                )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.data["detail"], "Si el correo está autorizado, recibirás un código"
        )

    def test_borrado_conserva_auditoria_sin_exponer_archivos(self):
        tesis = self.tesis(usuario=self.alumno, publicar=False)
        tesis.estado = Estado.RECHAZADA
        tesis.save()
        self.login(self.alumno)
        r = self.client.get(f"/api/tesis/{tesis.pk}/pdf/")
        list(r.streaming_content)
        r = self.client.delete(f"/api/tesis/{tesis.pk}/")
        self.assertEqual(r.status_code, 204)
        self.assertIsNone(RegistroAcceso.objects.get().tesis_id)

    def test_crear_superusuario_y_formulario_admin(self):
        from usuarios.forms import CrearUsuarioForm

        usuario = Usuario.objects.create_superuser(
            "super@inacap.cl", "Clave-fuerte-2026", nombre_completo="Super"
        )
        self.assertTrue(usuario.is_staff)
        self.assertEqual(usuario.rol, Rol.ADMIN)
        formulario = CrearUsuarioForm(
            data={
                "email": "form@inacap.cl",
                "nombre_completo": "Formulario",
                "rol": Rol.ADMIN,
                "password1": "Clave-formulario-2026",
                "password2": "Clave-formulario-2026",
            }
        )
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.save().email, "form@inacap.cl")
