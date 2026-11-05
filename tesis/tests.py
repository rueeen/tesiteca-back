from usuarios.tests_helpers import crear_usuario_activo
import json
import shutil
import tempfile
from io import BytesIO
from unittest.mock import patch
from django.test import override_settings
from django.conf import settings
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
from usuarios.models import Usuario, UsuarioAutorizado, Rol, IntentoLogin, EstadoCuenta
from .models import Tesis, Estado, MaterialAdicional, RegistroAcceso, TipoTrabajo
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
        "DEFAULT_THROTTLE_RATES": {
            "registro": "1000/hour",
            "login": "1000/min",
            "cuentas": "1000/min",
            "refresh": "1000/min",
            "ticket": "1000/min",
        },
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
        self.admin = crear_usuario_activo(
            "admin@inacap.cl", nombre_completo="Admin", rol=Rol.ADMIN, sede=self.sede
        )
        self.alumno = crear_usuario_activo(
            "alumno@inacapmail.cl",
            nombre_completo="Alumno AP",
            carrera=self.ap,
            sede=self.sede,
        )
        self.otro = crear_usuario_activo(
            "otro@inacapmail.cl",
            nombre_completo="Alumno IEI",
            carrera=self.iei,
            sede=self.sede,
        )
        self.coordinador = crear_usuario_activo(
            "coord@inacap.cl",
            nombre_completo="Coordinador",
            rol=Rol.COORDINADOR,
            carrera=self.ap,
            sede=self.sede,
        )
        self.director = crear_usuario_activo(
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
                "tipo": TipoTrabajo.PROYECTO_TITULO,
                "autoriza_publicacion": True,
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

    def preparar_password(self, usuario):
        usuario.set_password("Clave-demo-segura-2026")
        usuario.save()

    def test_inexistente_no_recibe_correo_y_respuesta_generica(self):
        r = self.client.post("/api/auth/recuperar/", {"email": "ausente@inacap.cl"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_dominio_rechazado(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/recuperar/", {"email": "alumno@gmail.com"}
            ).status_code,
            400,
        )

    def test_password_correcta_jwt_normalizacion_y_refresh(self):
        self.autorizar(self.alumno)
        self.preparar_password(self.alumno)
        r = self.client.post(
            "/api/auth/login/",
            {"email": self.alumno.email.upper(), "password": "Clave-demo-segura-2026"},
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotIn("refresh", r.data)
        token = r.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/auth/me/").data["rol"], Rol.ESTUDIANTE)
        self.client.credentials()
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            ).status_code,
            200,
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_cinco_intentos_y_expiracion(self):
        self.preparar_password(self.alumno)
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    "/api/auth/login/",
                    {"email": self.alumno.email, "password": "incorrecta"},
                ).status_code,
                401,
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/login/",
                {"email": self.alumno.email, "password": "Clave-demo-segura-2026"},
            ).status_code,
            429,
        )
        IntentoLogin.objects.update(creado=timezone.now() - timedelta(minutes=16))
        self.assertEqual(
            self.client.post(
                "/api/auth/login/",
                {"email": self.alumno.email, "password": "Clave-demo-segura-2026"},
            ).status_code,
            200,
        )

    def test_limite_recuperaciones_por_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(4):
                self.assertEqual(
                    self.client.post(
                        "/api/auth/recuperar/", {"email": self.alumno.email}
                    ).status_code,
                    200,
                )
        self.assertEqual(len(mail.outbox), 3)

    def test_desactivado_no_login(self):
        autorizado = self.autorizar(self.alumno)
        self.preparar_password(self.alumno)
        autorizado.activo = False
        autorizado.save()
        r = self.client.post(
            "/api/auth/login/",
            {"email": self.alumno.email, "password": "Clave-demo-segura-2026"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["codigo"], "desactivada")

    def excel(self, filas):
        libro = Workbook()
        libro.active.append(
            ["email", "rut", "nombre_completo", "carrera_codigo", "sede"]
        )
        for fila in filas:
            libro.active.append(fila)
        salida = BytesIO()
        libro.save(salida)
        return SimpleUploadedFile("lista.xlsx", salida.getvalue())

    def test_importacion_excel_upsert_errores(self):
        self.login(self.admin)
        filas = [
            ["nuevo@inacapmail.cl", "12345678-5", "Nuevo", "AP", "Arica"],
            ["malo@gmail.com", "", "Malo", "AP", "Arica"],
            ["sin@inacap.cl", "", "Sin carrera", "", "Arica"],
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
            ["ap@inacapmail.cl", "", "AP", "AP", "Arica"],
            ["iei@inacapmail.cl", "", "IEI", "IEI", "Arica"],
            ["admin@inacap.cl", "", "Admin", "", "Arica"],
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
            "tipo": TipoTrabajo.PROYECTO_TITULO,
            "autoriza_publicacion": True,
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
            ["ap@inacapmail.cl", "", "AP", "AP", "Arica"],
            ["enf@inacapmail.cl", "", "ENF", "ENF", "Arica"],
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
        with patch(
            "usuarios.cuentas.EmailMultiAlternatives.send",
            side_effect=OSError("SMTP no disponible"),
        ):
            with self.assertLogs("usuarios.cuentas", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    r = self.client.post(
                        "/api/auth/recuperar/", {"email": self.alumno.email}
                    )
        self.assertEqual(r.status_code, 200)

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

    def test_catalogo_tipos_con_nombres_del_modelo(self):
        self.login(self.alumno)
        r = self.client.get("/api/catalogos/tipos/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.data,
            [
                {"id": "PROYECTO_TITULO", "nombre": "Proyecto de título"},
                {"id": "PROYECTO_INTEGRADO", "nombre": "Proyecto integrado"},
            ],
        )
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/catalogos/tipos/").status_code, 401)

    def comprobar_contrato_detalle(self, datos):
        self.assertIsInstance(datos["palabras_clave"], list)
        for campo in ["carrera", "sede", "tipo", "subido_por"]:
            self.assertIsInstance(datos[campo], dict)
            self.assertIn("id", datos[campo])
        self.assertEqual(
            set(datos["carrera"]),
            {
                "id",
                "nombre",
                "codigo",
                "area",
                "permite_repositorio",
                "nivel_formacion",
                "duracion_semestres",
            },
        )
        self.assertEqual(set(datos["sede"]), {"id", "nombre", "ciudad", "region"})
        self.assertEqual(set(datos["tipo"]), {"id", "nombre"})
        self.assertEqual(set(datos["subido_por"]), {"id", "nombre_completo", "email"})
        for bandera in ["puede_editar", "puede_revisar", "puede_reenviar"]:
            self.assertIsInstance(datos[bandera], bool)
        self.assertIn("estado_nombre", datos)

    def test_contrato_detalle_listado_y_flags_por_rol(self):
        tesis = self.tesis(usuario=self.alumno, publicar=False)
        tesis.estado = Estado.RECHAZADA
        tesis.save()
        self.login(self.alumno)
        r = self.client.get(f"/api/tesis/{tesis.pk}/")
        self.comprobar_contrato_detalle(r.data)
        self.assertEqual(
            [r.data[c] for c in ["puede_editar", "puede_revisar", "puede_reenviar"]],
            [True, False, True],
        )
        propias = self.client.get("/api/tesis/mis-tesis/").data["results"]
        self.comprobar_contrato_detalle(propias[0])
        ajeno = crear_usuario_activo(
            "ajeno@inacapmail.cl",
            nombre_completo="Ajeno",
            carrera=self.ap,
            sede=self.sede,
        )
        self.login(ajeno)
        self.assertEqual(self.client.get(f"/api/tesis/{tesis.pk}/").status_code, 404)
        tesis.estado = Estado.PUBLICADA
        tesis.save()
        r = self.client.get(f"/api/tesis/{tesis.pk}/")
        self.assertEqual(
            [r.data[c] for c in ["puede_editar", "puede_revisar", "puede_reenviar"]],
            [False, False, False],
        )
        listado = self.client.get("/api/tesis/").data["results"][0]
        self.assertIsInstance(listado["carrera"], dict)
        self.assertIsInstance(listado["tipo"], dict)
        self.assertIsInstance(listado["palabras_clave"], list)
        tesis.estado = Estado.EN_REVISION
        tesis.save()
        self.login(self.coordinador)
        r = self.client.get(f"/api/tesis/{tesis.pk}/")
        self.assertEqual(
            [r.data[c] for c in ["puede_editar", "puede_revisar", "puede_reenviar"]],
            [True, True, False],
        )
        self.comprobar_contrato_detalle(
            self.client.get("/api/tesis/pendientes/").data["results"][0]
        )
        self.client.post(f"/api/tesis/{tesis.pk}/aprobar/")
        detalle = self.client.get(f"/api/tesis/{tesis.pk}/").data
        self.assertEqual(detalle["revisado_por"]["id"], self.coordinador.pk)
        self.assertFalse(detalle["puede_revisar"])

    def datos_subida(self, texto="Nueva tesis"):
        return {
            "titulo": texto,
            "resumen": "Resumen",
            "tipo": TipoTrabajo.PROYECTO_TITULO,
            "autoriza_publicacion": True,
            "anio": 2026,
            "carrera": self.ap.pk,
            "profesor_guia": "Guía",
            "autores": "[]",
            "pdf": pdf_demo(texto),
        }

    def test_post_sin_sede_y_normalizacion_palabras_clave(self):
        self.login(self.alumno)
        for numero, valor in enumerate(
            [" iot, web, IOT, ,web ", '["iot", "web", "IOT", "", " web "]']
        ):
            with self.subTest(valor=valor):
                datos = self.datos_subida(f"Palabras {numero}")
                datos["palabras_clave"] = valor
                r = self.client.post("/api/tesis/", datos, format="multipart")
                self.assertEqual(r.status_code, 201, r.data)
                self.assertEqual(r.data["sede"]["id"], self.sede.pk)
                self.assertEqual(r.data["palabras_clave"], ["iot", "web"])
                self.comprobar_contrato_detalle(r.data)
                self.assertEqual(
                    Tesis.objects.get(pk=r.data["id"]).palabras_clave, "iot,web"
                )

    def test_sede_unica_ambigua_inactiva_y_explicita(self):
        self.admin.sede = None
        self.admin.save()
        self.login(self.admin)
        r = self.client.post(
            "/api/tesis/", self.datos_subida("Sede única"), format="multipart"
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["sede"]["id"], self.sede.pk)
        otra = Sede.objects.create(nombre="Otra", ciudad="Otra")
        r = self.client.post(
            "/api/tesis/", self.datos_subida("Ambigua"), format="multipart"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("sede", r.data)
        datos = self.datos_subida("Sede explícita")
        datos["sede"] = otra.pk
        r = self.client.post("/api/tesis/", datos, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["sede"]["id"], otra.pk)
        Sede.objects.all().update(activa=False)
        r = self.client.post(
            "/api/tesis/", self.datos_subida("Sin activas"), format="multipart"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("sede", r.data)

    def test_patch_responde_contrato_y_autores_actualizados(self):
        tesis = self.tesis(usuario=self.alumno, publicar=False)
        tesis.estado = Estado.RECHAZADA
        tesis.save()
        self.login(self.alumno)
        r = self.client.patch(
            f"/api/tesis/{tesis.pk}/",
            {
                "palabras_clave": '["iot","web","IOT"]',
                "autores": '[{"nombre_completo":"Coautora nueva","email":"nueva@inacapmail.cl"}]',
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.comprobar_contrato_detalle(r.data)
        self.assertEqual(r.data["palabras_clave"], ["iot", "web"])
        self.assertIn(
            "Coautora nueva", [autor["nombre_completo"] for autor in r.data["autores"]]
        )
        tesis.refresh_from_db()
        self.assertEqual(tesis.palabras_clave, "iot,web")

    def test_palabras_clave_json_invalido_y_lectura_legacy(self):
        from .palabras_clave import PalabrasClaveField, palabras_clave_lista
        from rest_framework.exceptions import ValidationError

        campo = PalabrasClaveField()
        for valor in ['["iot",', '[1,"web"]', {"iot": True}, "a" * 501]:
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                campo.to_internal_value(valor)
        self.assertEqual(palabras_clave_lista('["iot", "web", "IOT"]'), ["iot", "web"])
        tesis = self.tesis()
        tesis.palabras_clave = '["iot", "web"]'
        tesis.save()
        self.login(self.alumno)
        self.assertEqual(
            self.client.get(f"/api/tesis/{tesis.pk}/").data["palabras_clave"],
            ["iot", "web"],
        )
        self.assertEqual(
            self.client.get("/api/tesis/").data["results"][0]["palabras_clave"],
            ["iot", "web"],
        )

    def test_me_y_login_con_objetos_anidados_y_nulos(self):
        self.login(self.alumno)
        datos = self.client.get("/api/auth/me/").data
        self.assertEqual(datos["carrera"]["nombre"], self.ap.nombre)
        self.assertEqual(datos["sede"]["nombre"], "Arica")
        self.assertEqual(datos["sede"]["region"]["id"], "XV")
        self.assertIsNone(datos["area"])
        self.login(self.director)
        datos = self.client.get("/api/auth/me/").data
        self.assertIsNone(datos["carrera"])
        self.assertEqual(datos["area"]["id"], self.area.id)
        self.client.force_authenticate(None)
        self.autorizar(self.alumno)
        self.preparar_password(self.alumno)
        r = self.client.post(
            "/api/auth/login/",
            {"email": self.alumno.email, "password": "Clave-demo-segura-2026"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["usuario"]["carrera"]["nombre"], self.ap.nombre)

    def test_autorizados_ids_en_escritura_objetos_en_lectura_y_errores_legibles(self):
        self.login(self.admin)
        r = self.client.post(
            "/api/admin/autorizados/",
            {
                "email": "nuevo@inacapmail.cl",
                "nombre_completo": "Nuevo",
                "rol": "ESTUDIANTE",
                "carrera": self.ap.id,
                "sede": self.sede.id,
            },
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["carrera"]["codigo"], "AP")
        pk = r.data["id"]
        r = self.client.patch(f"/api/admin/autorizados/{pk}/", {"carrera": self.iei.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["carrera"]["codigo"], "IEI")
        self.assertEqual(
            self.client.get("/api/admin/autorizados/").data["results"][0]["sede"][
                "nombre"
            ],
            "Arica",
        )
        filas = [["no-es-email", "", "Inválido", "AP", "Arica"]]
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": self.excel(filas)},
            format="multipart",
        )
        self.assertEqual(len(r.data["errores"]), 1)
        motivo = r.data["errores"][0]["motivo"]
        self.assertTrue(motivo.startswith("email: "), motivo)
        self.assertNotIn("ErrorDetail", motivo)
        self.assertNotIn("{'", motivo)

    def test_marca_pdf_con_origen_desplazado(self):
        original = pdf_demo("Origen desplazado")
        lector = PdfReader(original)
        escritor = PdfWriter()
        for pagina in lector.pages:
            pagina.mediabox.lower_left = (50, 50)
            pagina.mediabox.upper_right = (500, 750)
            escritor.add_page(pagina)
        salida = BytesIO()
        escritor.write(salida)
        tesis = self.tesis(pdf=SimpleUploadedFile("desplazado.pdf", salida.getvalue()))
        posiciones = []

        def visitar(texto, cm, tm, fuente, tamano):
            if "Prohibida su reproducción" in texto or "Consultado por" in texto:
                posiciones.append((texto, cm[4] + tm[4], cm[5] + tm[5]))

        with tesis.pdf_marcado.open("rb") as marcado:
            lector = PdfReader(marcado)
            self.assertEqual(tuple(lector.pages[0].mediabox), (50, 50, 500, 750))
            self.assertEqual(len(lector.pages), 2)
            for pagina in lector.pages:
                pagina.extract_text(visitor_text=visitar)
            self.assertEqual([pos[2] for pos in posiciones], [60, 60])
        with tesis.pdf_marcado.open("rb") as marcado:
            salida = aplicar_marca_lector(marcado, self.alumno, "127.0.0.1")
        posiciones.clear()
        pagina = PdfReader(salida).pages[0]
        texto = pagina.extract_text(visitor_text=visitar)
        self.assertIn("INACAP", texto)
        self.assertIn(self.alumno.email, texto)
        lector_pos = [p for p in posiciones if "Consultado por" in p[0]]
        self.assertEqual((lector_pos[0][1], lector_pos[0][2]), (63, 733.5))

    def test_serializacion_detalle_sin_n_mas_uno(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from types import SimpleNamespace
        from .permisos import visibles
        from .serializers import TesisDetalleSerializer

        for i in range(4):
            tesis = self.tesis(
                titulo=f"Consulta {i}", usuario=self.alumno, publicar=False
            )
            tesis.estado = Estado.RECHAZADA
            tesis.save()
            MaterialAdicional.objects.create(
                tesis=tesis,
                tipo="REPOSITORIO",
                titulo="Repo",
                url="https://github.com/demo/demo",
            )

        def medir(limite):
            qs = (
                Tesis.objects.select_related(
                    "carrera__area", "sede", "subido_por", "revisado_por"
                )
                .prefetch_related("autores", "materiales")
                .order_by("id")[:limite]
            )
            with CaptureQueriesContext(connection) as consultas:
                datos = TesisDetalleSerializer(
                    qs, many=True, context={"request": SimpleNamespace(user=self.otro)}
                ).data
                self.assertEqual(len(datos), limite)
            return len(consultas)

        self.assertEqual(medir(1), medir(4))

    def test_seed_coherente_idempotente_y_reset_archivos(self):
        from django.core.management import call_command
        from pathlib import Path

        def sembrar(reset=False):
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    "seed_demo",
                    con_ejemplos=True,
                    reset_ejemplos=reset,
                    stdout=__import__("io").StringIO(),
                )

        sembrar()
        ejemplos = Tesis.objects.filter(titulo__startswith="Demo ")
        self.assertEqual(ejemplos.count(), 15)
        self.assertEqual(
            ejemplos.filter(tipo=TipoTrabajo.PROYECTO_INTEGRADO).count(), 8
        )
        self.assertEqual(ejemplos.filter(tipo=TipoTrabajo.PROYECTO_TITULO).count(), 7)
        self.assertEqual(ejemplos.filter(estado=Estado.PUBLICADA).count(), 11)
        self.assertEqual(ejemplos.filter(estado=Estado.EN_REVISION).count(), 3)
        self.assertEqual(ejemplos.filter(estado=Estado.RECHAZADA).count(), 1)
        for tesis in ejemplos.select_related("subido_por"):
            self.assertEqual(tesis.subido_por.carrera_id, tesis.carrera_id)
            self.assertEqual(
                tesis.subido_por.rol,
                Rol.COORDINADOR if tesis.estado == Estado.PUBLICADA else Rol.ESTUDIANTE,
            )
            for autor in tesis.autores.select_related("usuario"):
                if autor.usuario:
                    self.assertEqual(autor.usuario.carrera_id, tesis.carrera_id)
        alumno_iei = Usuario.objects.get(email="demo1@inacapmail.cl")
        self.assertEqual(alumno_iei.estado_cuenta, "PENDIENTE_VERIFICACION")
        self.assertIsNone(alumno_iei.email_verificado_en)
        self.assertEqual(alumno_iei.solicitud.estado, "APROBADA")
        self.assertEqual(alumno_iei.carrera.codigo, "IEI")
        self.login(alumno_iei)
        r = self.client.get("/api/tesis/?page_size=48")
        self.assertGreater(r.data["count"], 0)
        self.assertTrue(all(t["carrera"]["codigo"] == "IEI" for t in r.data["results"]))
        propias = self.client.get("/api/tesis/mis-tesis/").data["results"]
        rechazada = next(t for t in propias if t["estado"] == Estado.RECHAZADA)
        self.assertTrue(rechazada["puede_reenviar"])
        self.assertTrue(rechazada["observacion_revision"])
        coordinador = Usuario.objects.get(email="demo5@inacapmail.cl")
        self.login(coordinador)
        pendientes = self.client.get("/api/tesis/pendientes/").data
        self.assertGreater(pendientes["count"], 0)
        self.assertTrue(
            all(t["carrera"]["codigo"] == "IEI" for t in pendientes["results"])
        )
        impar = ejemplos.get(titulo="Demo 01: Biblioteca tecnológica de Arica")
        ruta_original = impar.pdf_original.name
        Tesis.objects.filter(pk=impar.pk).update(tipo=TipoTrabajo.PROYECTO_TITULO)
        sembrar()
        self.assertEqual(ejemplos.count(), 15)
        impar.refresh_from_db()
        self.assertEqual(impar.tipo, TipoTrabajo.PROYECTO_INTEGRADO)
        self.assertEqual(impar.pdf_original.name, ruta_original)
        self.assertEqual(
            ejemplos.filter(tipo=TipoTrabajo.PROYECTO_INTEGRADO).count(), 8
        )
        anterior = set(ejemplos.values_list("pdf_original", flat=True)) | set(
            ejemplos.values_list("pdf_marcado", flat=True)
        )
        sembrar(True)
        self.assertEqual(ejemplos.count(), 15)
        self.assertTrue(all(not privado.exists(nombre) for nombre in anterior))
        sembrar(True)
        self.assertEqual(ejemplos.count(), 15)
        self.assertEqual(len(list(Path(self.directorio).rglob("*.pdf"))), 30)

    def test_notificaciones_revision_aprobacion_rechazo_y_reenvio(self):
        from notificaciones.models import Notificacion, TipoNotificacion

        tesis = self.tesis(usuario=self.alumno, publicar=False)
        destinatarios = set(
            Notificacion.objects.filter(
                tipo=TipoNotificacion.TESIS_EN_REVISION
            ).values_list("usuario_id", flat=True)
        )
        self.assertEqual(destinatarios, {self.coordinador.id, self.director.id})
        tesis.autores.create(
            nombre_completo=self.otro.nombre_completo,
            email=self.otro.email,
            usuario=self.otro,
        )
        self.login(self.coordinador)
        self.assertEqual(
            self.client.post(
                f"/api/tesis/{tesis.pk}/rechazar/",
                {"observacion": "Corregir referencias"},
            ).status_code,
            200,
        )
        rechazadas = Notificacion.objects.filter(tipo=TipoNotificacion.TESIS_RECHAZADA)
        self.assertEqual(
            set(rechazadas.values_list("usuario_id", flat=True)),
            {self.alumno.id, self.otro.id},
        )
        self.assertIn("Corregir referencias", rechazadas.first().mensaje)
        self.login(self.alumno)
        self.assertEqual(
            self.client.post(f"/api/tesis/{tesis.pk}/reenviar/").status_code, 200
        )
        self.assertEqual(
            set(
                Notificacion.objects.filter(
                    tipo=TipoNotificacion.TESIS_REENVIADA
                ).values_list("usuario_id", flat=True)
            ),
            {self.coordinador.id, self.director.id},
        )
        self.login(self.coordinador)
        self.assertEqual(
            self.client.post(f"/api/tesis/{tesis.pk}/aprobar/").status_code, 200
        )
        self.assertEqual(
            set(
                Notificacion.objects.filter(
                    tipo=TipoNotificacion.TESIS_APROBADA
                ).values_list("usuario_id", flat=True)
            ),
            {self.alumno.id, self.otro.id},
        )

    def test_fallo_ws_y_smtp_no_rompe_aprobacion(self):
        from notificaciones.models import Notificacion, TipoNotificacion
        from channels.layers import get_channel_layer
        from unittest.mock import AsyncMock

        tesis = self.tesis(usuario=self.alumno, publicar=False)
        self.login(self.coordinador)
        with override_settings(NOTIFICACIONES_WS=True, NOTIFICAR_POR_CORREO=True):
            with patch.object(
                get_channel_layer(),
                "group_send",
                new=AsyncMock(side_effect=RuntimeError("Redis caído")),
            ):
                with patch(
                    "notificaciones.servicios.send_mail",
                    side_effect=OSError("SMTP caído"),
                ):
                    with self.assertLogs("notificaciones.servicios", level="ERROR"):
                        with self.captureOnCommitCallbacks(execute=True):
                            r = self.client.post(f"/api/tesis/{tesis.pk}/aprobar/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.alumno, tipo=TipoNotificacion.TESIS_APROBADA
            ).exists()
        )

    def test_notificar_deduplica_omite_actor_inactivos_y_rollback(self):
        from notificaciones.servicios import notificar
        from notificaciones.models import Notificacion
        from django.db import transaction

        self.otro.cambiar_estado(EstadoCuenta.DESACTIVADA)
        with override_settings(NOTIFICACIONES_WS=False, NOTIFICAR_POR_CORREO=True):
            with self.captureOnCommitCallbacks(execute=True):
                creadas = notificar(
                    [self.alumno, self.alumno, self.coordinador, self.otro],
                    "TESIS_APROBADA",
                    "Aprobada",
                    "Mensaje",
                    "/tesis/1",
                    actor=self.coordinador,
                )
        self.assertEqual(len(creadas), 1)
        self.assertEqual(creadas[0].usuario_id, self.alumno.id)
        self.assertEqual(len(mail.outbox), 0)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                notificar(
                    [self.alumno],
                    "TESIS_APROBADA",
                    "No persistir",
                    "Mensaje",
                    "/tesis/2",
                )
                raise RuntimeError("Revertir")
        self.assertEqual(Notificacion.objects.count(), 1)

    def test_api_notificaciones_propias_y_polling_sin_ws(self):
        from notificaciones.models import Notificacion

        self.login(self.alumno)
        propias = [
            Notificacion.objects.create(
                usuario=self.alumno,
                tipo="TESIS_APROBADA",
                titulo=f"Título {i}",
                mensaje="Mensaje",
                enlace="/tesis/1",
            )
            for i in range(3)
        ]
        ajena = Notificacion.objects.create(
            usuario=self.otro,
            tipo="TESIS_APROBADA",
            titulo="Ajena",
            mensaje="Mensaje",
            enlace="/tesis/1",
        )
        with override_settings(NOTIFICACIONES_WS=False):
            self.assertEqual(
                self.client.get("/api/notificaciones/resumen/").data,
                {"no_leidas": 3, "ultima_id": propias[-1].id},
            )
            r = self.client.get(
                f"/api/notificaciones/?leida=false&desde_id={propias[0].id}"
            )
            self.assertEqual(
                [n["id"] for n in r.data["results"]], [propias[2].id, propias[1].id]
            )
            self.assertEqual(
                self.client.post(f"/api/notificaciones/{ajena.pk}/leer/").status_code,
                404,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/notificaciones/{propias[0].pk}/leer/"
                ).status_code,
                204,
            )
            self.assertEqual(
                self.client.post("/api/notificaciones/leer-todas/").data,
                {"actualizadas": 2},
            )
            self.assertEqual(
                self.client.get("/api/notificaciones/resumen/").data["no_leidas"], 0
            )
            self.assertEqual(
                self.client.get("/api/notificaciones/?leida=true").data["count"], 3
            )
            self.assertEqual(
                self.client.get("/api/notificaciones/?desde_id=abc").status_code, 400
            )
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/notificaciones/").status_code, 401)

    def test_importacion_activo_false_revoca_sesiones(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        autorizado = self.autorizar(self.alumno)
        token = RefreshToken.for_user(self.alumno)
        self.login(self.admin)
        csv = (
            "email,rut,nombre_completo,carrera_codigo,sede,activo\n"
            + f"{self.alumno.email},,Alumno,AP,Arica,false\n"
        )
        r = self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": SimpleUploadedFile("lista.csv", csv.encode())},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["actualizados"], 1)
        self.alumno.refresh_from_db()
        self.assertFalse(self.alumno.is_active)
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
        )

    def test_pdf_preserva_cache_control_y_varia_por_sesion(self):
        tesis = self.tesis()
        self.login(self.alumno)
        r = self.client.get(f"/api/tesis/{tesis.pk}/pdf/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertTrue(
            {"authorization", "cookie"}.issubset(
                {v.strip().lower() for v in r["Vary"].split(",")}
            )
        )
        r.close()

    def test_alcance_sede_visibilidad_region_y_periodo(self):
        otra_sede = Sede.objects.create(
            nombre="Otra sede", ciudad="Santiago", region="RM", orden=7
        )
        tesis = self.tesis(titulo="Tesis de otra sede", publicar=False)
        tesis.sede = otra_sede
        tesis.periodo = 2
        tesis.save()
        self.login(self.coordinador)
        self.assertEqual(self.client.get("/api/tesis/pendientes/").data["count"], 0)
        self.assertEqual(
            self.client.post(f"/api/tesis/{tesis.pk}/aprobar/").status_code, 404
        )
        tesis.estado = Estado.PUBLICADA
        tesis.save()
        self.login(self.alumno)
        with override_settings(VISIBILIDAD_ENTRE_SEDES=True):
            r = self.client.get("/api/tesis/?region=RM")
            self.assertEqual(r.data["count"], 1)
            self.assertEqual(
                r.data["results"][0]["periodo"], {"id": 2, "nombre": "Segundo semestre"}
            )
            self.assertEqual(
                r.data["results"][0]["periodo_texto"], "2025 · Segundo semestre"
            )
            self.assertEqual(self.client.get("/api/tesis/?region=XV").data["count"], 0)
        with override_settings(VISIBILIDAD_ENTRE_SEDES=False):
            self.assertEqual(self.client.get("/api/tesis/").data["count"], 0)
        self.ap.nivel_formacion = "TECNICO"
        self.ap.save()
        with override_settings(VISIBILIDAD_ENTRE_SEDES=True):
            self.assertEqual(
                self.client.get("/api/tesis/?nivel_formacion=TECNICO").data["count"], 1
            )
            self.assertEqual(
                self.client.get("/api/tesis/?nivel_formacion=INGENIERIA").data["count"],
                0,
            )

    def test_resumen_normalizado_y_listado_limite_palabra(self):
        from .texto import normalizar_resumen, resumen_breve

        texto = "  Esta infor-\r\nmación   se pegó de un PDF y corta\nla frase a la mitad.\nSegundo párrafo.\n\n\n- Primera viñeta\n• Segunda viñeta\n1) Tercera viñeta"
        esperado = "Esta información se pegó de un PDF y corta la frase a la mitad.\n\nSegundo párrafo.\n\n- Primera viñeta\n\n• Segunda viñeta\n\n1) Tercera viñeta"
        self.assertEqual(normalizar_resumen(texto), esperado)
        self.assertEqual(normalizar_resumen(esperado), esperado)
        largo = "palabra larga " * 40
        resumen = resumen_breve(largo)
        self.assertLessEqual(len(resumen), 280)
        self.assertTrue(resumen.endswith("…"))
        self.assertTrue(largo.startswith(resumen[:-1]))
        self.login(self.admin)
        tesis = self.tesis()
        r = self.client.patch(f"/api/tesis/{tesis.pk}/", {"resumen": texto})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["resumen"], esperado)

    def test_notificaciones_y_autorizados_no_cruzan_sedes(self):
        otra_sede = Sede.objects.create(nombre="Otra sede", ciudad="Otra", region="I")
        otro_coord = crear_usuario_activo(
            "coord-otra@inacap.cl",
            nombre_completo="Otra sede",
            rol=Rol.COORDINADOR,
            carrera=self.ap,
            sede=otra_sede,
        )
        self.tesis(usuario=self.alumno, publicar=False)
        from notificaciones.models import Notificacion

        self.assertFalse(Notificacion.objects.filter(usuario=otro_coord).exists())
        autorizado = UsuarioAutorizado.objects.create(
            email="autorizado-otra@inacapmail.cl",
            nombre_completo="Otra",
            carrera=self.ap,
            sede=otra_sede,
        )
        self.login(self.coordinador)
        self.assertEqual(self.client.get("/api/admin/autorizados/").data["count"], 0)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{autorizado.pk}/", {"activo": False}
            ).status_code,
            404,
        )

    def test_normalizar_resumen_casos_normativos_e_idempotencia(self):
        from pathlib import Path
        from .texto import normalizar_resumen
        import importlib

        casos = json.loads(
            (
                Path(__file__).parent / "tests_fixtures" / "resumen_casos.json"
            ).read_text()
        )
        migracion = importlib.import_module(
            "tesis.migrations.0006_renormalizar_resumen"
        )
        self.assertEqual(len(casos), 10)
        for caso in casos:
            with self.subTest(id=caso["id"]):
                resultado = normalizar_resumen(caso["entrada"])
                self.assertEqual(resultado, caso["esperado"])
                self.assertEqual(normalizar_resumen(resultado), resultado)
                self.assertEqual(
                    migracion.normalizar_resumen(caso["entrada"]), resultado
                )
                self.assertEqual(migracion.normalizar_resumen(resultado), resultado)
        self.assertEqual(normalizar_resumen(None), "")
        self.assertEqual(normalizar_resumen(""), "")

    def test_listado_incluye_sede_y_consultas_constantes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.login(self.admin)
        for i in range(2):
            self.tesis(titulo=f"Listado con sede {i}")
        with CaptureQueriesContext(connection) as consultas:
            inicial = self.client.get("/api/tesis/")
        cantidad_consultas = len(consultas)
        self.assertEqual(inicial.status_code, 200)
        self.assertEqual(inicial.data["count"], 2)

        for i in range(2, 10):
            self.tesis(titulo=f"Listado con sede {i}")
        with self.assertNumQueries(cantidad_consultas):
            completo = self.client.get("/api/tesis/")
        self.assertEqual(completo.status_code, 200)
        self.assertEqual(completo.data["count"], 10)
        self.assertEqual(len(completo.data["results"]), 10)
        esperado = {
            "id": self.sede.pk,
            "nombre": "Arica",
            "ciudad": "Arica",
            "region": {"id": "XV", "nombre": "Arica y Parinacota"},
        }
        for respuesta in (inicial, completo):
            for item in respuesta.data["results"]:
                with self.subTest(tesis=item["id"]):
                    self.assertEqual(item["sede"], esperado)
                    self.assertEqual(item["sede"]["nombre"], "Arica")
                    self.assertEqual(
                        item["sede"]["region"]["nombre"], "Arica y Parinacota"
                    )

    def test_marcas_visibles_en_crop_rotacion_fondo_negro_y_horizontal(self):
        from reportlab.lib.pagesizes import A4, landscape
        from .marca_agua import TEXTO_DIAGONAL
        from math import isclose

        salida = BytesIO()
        lienzo = canvas.Canvas(salida, pagesize=A4)
        for i in range(5):
            lienzo.setPageSize(landscape(A4) if i == 4 else A4)
            if i == 3:
                lienzo.setFillColorRGB(0, 0, 0)
                lienzo.rect(0, 0, *A4, fill=1, stroke=0)
            lienzo.showPage()
        lienzo.save()
        lector = PdfReader(BytesIO(salida.getvalue()))
        escritor = PdfWriter()
        for i, pagina in enumerate(lector.pages):
            if i == 1:
                pagina.cropbox.lower_left = (60, 80)
                pagina.cropbox.upper_right = (520, 760)
            if i == 2:
                pagina.rotate(90)
            escritor.add_page(pagina)
        original = BytesIO()
        escritor.write(original)
        tesis = self.tesis(pdf=SimpleUploadedFile("variadas.pdf", original.getvalue()))
        with tesis.pdf_marcado.open("rb") as archivo:
            fijo = archivo.read()

        def comprobar(datos, lector_personal=False):
            lector = PdfReader(BytesIO(datos))
            self.assertEqual(len(lector.pages), 5)
            for numero, pagina in enumerate(lector.pages):
                posiciones = []

                def visitar(texto, cm, tm, fuente, tamano):
                    if (
                        TEXTO_DIAGONAL in texto
                        or "Prohibida su reproducción" in texto
                        or "Consultado por" in texto
                    ):
                        x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
                        y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
                        posiciones.append((texto, x, y))

                texto = pagina.extract_text(visitor_text=visitar)
                with self.subTest(pagina=numero, lector=lector_personal):
                    self.assertGreaterEqual(texto.count(TEXTO_DIAGONAL), 3)
                    self.assertIn("Prohibida su reproducción", texto)
                    if lector_personal:
                        self.assertIn("Consultado por", texto)
                    caja = pagina.cropbox
                    for etiqueta, x, y in posiciones:
                        self.assertTrue(
                            float(caja.left) <= x <= float(caja.right),
                            (etiqueta, x, caja),
                        )
                        self.assertTrue(
                            float(caja.bottom) <= y <= float(caja.top),
                            (etiqueta, y, caja),
                        )
                    self.assertIn(b"2 Tr", pagina.get_contents().get_data())
                    estados = pagina["/Resources"]["/ExtGState"].values()
                    self.assertTrue(
                        any(isclose(float(e.get("/CA", 0)), 0.35) for e in estados)
                    )

        comprobar(fijo)
        marcado = aplicar_marca_lector(BytesIO(fijo), self.alumno, "127.0.0.1")
        comprobar(marcado.getvalue(), True)

    def test_regenerar_marcas_filtra_y_continua_si_falla(self):
        from django.core.management import call_command
        from io import StringIO

        a = self.tesis(titulo="Para regenerar A")
        b = self.tesis(titulo="Para regenerar B")
        salida = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("regenerar_marcas", id=a.pk, stdout=salida)
        a.refresh_from_db()
        self.assertIn("Regeneradas: 1", salida.getvalue())
        from .marca_agua import regenerar_marca

        def regeneracion(tesis):
            if tesis.pk == a.pk:
                raise OSError("Original no disponible")
            return regenerar_marca(tesis)

        with patch(
            "tesis.management.commands.regenerar_marcas.regenerar_marca",
            side_effect=regeneracion,
        ):
            with self.assertLogs(
                "tesis.management.commands.regenerar_marcas", level="ERROR"
            ):
                salida = StringIO()
                errores = StringIO()
                with self.captureOnCommitCallbacks(execute=True):
                    call_command("regenerar_marcas", stdout=salida, stderr=errores)
        self.assertIn("Regeneradas: 1; errores: 1; total: 2", salida.getvalue())

    def test_rechaza_tipos_retirados_y_desconocidos_en_post_y_patch(self):
        import importlib

        anterior = importlib.import_module("tesis.migrations.0004_alter_tesis_tipo")
        retirados = [
            codigo
            for codigo, _ in anterior.Migration.operations[0].field.choices
            if codigo not in TipoTrabajo.values
        ]
        self.assertEqual(len(retirados), 2)
        self.login(self.admin)
        tesis = self.tesis(titulo="Tipo válido")
        for tipo in retirados + ["OTRO_INVALIDO"]:
            with self.subTest(tipo=tipo):
                datos = self.datos_subida("Subida inválida")
                datos["tipo"] = tipo
                post = self.client.post("/api/tesis/", datos, format="multipart")
                patch = self.client.patch(f"/api/tesis/{tesis.pk}/", {"tipo": tipo})
                for respuesta in [post, patch]:
                    self.assertEqual(respuesta.status_code, 400, respuesta.data)
                    self.assertIn(
                        "Tipo de trabajo inválido", str(respuesta.data["tipo"])
                    )
        tesis.refresh_from_db()
        self.assertEqual(tesis.tipo, TipoTrabajo.PROYECTO_TITULO)
        self.assertEqual(Tesis.objects.count(), 1)

    def test_filtro_proyecto_integrado_y_detalle(self):
        titulo = self.tesis(titulo="Proyecto de título")
        integrado = self.tesis(titulo="Proyecto integrado")
        integrado.tipo = TipoTrabajo.PROYECTO_INTEGRADO
        integrado.save(update_fields=["tipo"])
        self.login(self.alumno)
        r = self.client.get("/api/tesis/", {"tipo": TipoTrabajo.PROYECTO_INTEGRADO})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([item["id"] for item in r.data["results"]], [integrado.pk])
        self.assertEqual(
            r.data["results"][0]["tipo"],
            {"id": "PROYECTO_INTEGRADO", "nombre": "Proyecto integrado"},
        )
        self.assertEqual(
            self.client.get(f"/api/tesis/{integrado.pk}/").data["tipo"],
            r.data["results"][0]["tipo"],
        )
        self.login(self.admin)
        cambio = self.client.patch(
            f"/api/tesis/{titulo.pk}/", {"tipo": TipoTrabajo.PROYECTO_INTEGRADO}
        )
        self.assertEqual(cambio.status_code, 200, cambio.data)
        self.assertEqual(cambio.data["tipo"]["id"], TipoTrabajo.PROYECTO_INTEGRADO)
