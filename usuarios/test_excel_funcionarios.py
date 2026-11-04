from io import BytesIO
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from academico.models import Area, Carrera, Sede
from .models import Usuario, UsuarioAutorizado, SolicitudAcceso, Rol, EstadoCuenta
from .tests_helpers import crear_usuario_activo
from .cuentas import token_verificacion

COLUMNAS = ["email", "rut", "nombre_completo", "carrera_codigo", "sede"]
CLAVE = "Funcionario-seguro-2026!"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ExcelFuncionariosTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.area = Area.objects.create(nombre="Informática")
        self.otra_area = Area.objects.create(nombre="Otra área")
        self.carrera = Carrera.objects.create(
            nombre="Ingeniería", codigo="IEI", area=self.area
        )
        self.ap = Carrera.objects.create(nombre="Analista", codigo="AP", area=self.area)
        self.otra_carrera = Carrera.objects.create(
            nombre="Otra carrera", codigo="OTRA", area=self.otra_area
        )
        self.sede = Sede.objects.create(nombre="Arica", ciudad="Arica")
        self.otra_sede = Sede.objects.create(nombre="Otra sede", ciudad="Otra")
        self.admin = crear_usuario_activo(
            "admin@inacap.cl", CLAVE, rol=Rol.ADMIN, nombre_completo="Administrador"
        )
        self.director = crear_usuario_activo(
            "director@inacap.cl",
            rol=Rol.DIRECTOR,
            nombre_completo="Director",
            area=self.area,
            sede=self.sede,
        )
        self.coord = crear_usuario_activo(
            "coord@inacap.cl",
            rol=Rol.COORDINADOR,
            nombre_completo="Coordinador",
            carrera=self.carrera,
            sede=self.sede,
        )
        self.client.force_authenticate(self.admin)

    def archivo(self, filas, columnas=None):
        libro = Workbook()
        libro.active.append(columnas or COLUMNAS)
        for fila in filas:
            libro.active.append(fila)
        salida = BytesIO()
        libro.save(salida)
        return SimpleUploadedFile("alumnos.xlsx", salida.getvalue())

    def importar(self, filas, columnas=None):
        return self.client.post(
            "/api/admin/autorizados/importar/",
            {"archivo": self.archivo(filas, columnas)},
            format="multipart",
        )

    def funcionario(self, **extra):
        return {
            "email": "nuevo@inacap.cl",
            "nombre_completo": "Nombre del funcionario",
            "rol": "COORDINADOR",
            "carrera": self.carrera.pk,
            "sede": self.sede.pk,
            **extra,
        }

    def cuenta_pendiente(self, email, verificada=False):
        u = Usuario.objects.create_user(
            email,
            CLAVE,
            nombre_completo="Cuenta existente",
            rol=Rol.COORDINADOR,
            carrera=self.carrera,
            area=self.area,
            sede=self.sede,
        )
        SolicitudAcceso.objects.create(
            usuario=u,
            rol_solicitado=Rol.COORDINADOR,
            carrera=self.carrera,
            sede=self.sede,
        )
        if verificada:
            u.email_verificado_en = timezone.now()
            u.save(update_fields=["email_verificado_en"])
            u.cambiar_estado(EstadoCuenta.PENDIENTE_APROBACION)
        return u

    def test_plantilla_instrucciones_y_catalogos(self):
        r = self.client.get("/api/admin/autorizados/plantilla/")
        libro = load_workbook(BytesIO(r.content))
        self.assertEqual([c.value for c in libro.active[1]], COLUMNAS)
        self.assertEqual(
            libro.sheetnames, ["Estudiantes", "Instrucciones", "Carreras", "Sedes"]
        )
        self.assertIn(
            "IEI",
            [
                fila[0]
                for fila in libro["Carreras"].iter_rows(min_row=2, values_only=True)
            ],
        )
        self.assertIn(
            "Arica",
            [fila[0] for fila in libro["Sedes"].iter_rows(min_row=2, values_only=True)],
        )
        self.assertIn(
            "@inacapmail.cl",
            " ".join(str(c.value) for fila in libro["Instrucciones"] for c in fila),
        )
        libro.close()

    def test_excel_solo_estudiantes_area_derivada_y_rut_validado(self):
        r = self.importar(
            [
                ["alumno@inacapmail.cl", "12.345.678-5", "Alumno", "IEI", "ARÍCA"],
                ["malrut@inacapmail.cl", "12345678-9", "RUT malo", "IEI", "Arica"],
                ["funcionario@inacap.cl", "", "Funcionario", "IEI", "Arica"],
                ["sin-carrera@inacapmail.cl", "", "Sin carrera", "", "Arica"],
                ["sin-sede@inacapmail.cl", "", "Sin sede", "IEI", ""],
            ]
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["creados"], 1)
        self.assertEqual(len(r.data["errores"]), 4)
        self.assertIn(
            "Los funcionarios se registran desde el formulario de funcionarios",
            r.data["errores"][1]["motivo"],
        )
        a = UsuarioAutorizado.objects.get(email="alumno@inacapmail.cl")
        self.assertEqual(a.rol, "ESTUDIANTE")
        self.assertEqual(a.area, self.area)
        self.assertEqual(a.rut, "12345678-5")

    def test_excel_no_modifica_funcionarios_y_rechaza_plantilla_antigua(self):
        a = UsuarioAutorizado.objects.create(
            email="legacy@inacapmail.cl",
            nombre_completo="Funcionario heredado",
            rol=Rol.COORDINADOR,
            carrera=self.carrera,
            sede=self.sede,
        )
        r = self.importar([[a.email, "", "Modificado", "IEI", "Arica"]])
        self.assertIn(
            "No se puede modificar un funcionario desde Excel",
            r.data["errores"][0]["motivo"],
        )
        a.refresh_from_db()
        self.assertEqual(a.nombre_completo, "Funcionario heredado")
        self.assertEqual(a.rol, Rol.COORDINADOR)
        for antiguas in [
            [
                "email",
                "rut",
                "nombre_completo",
                "rol",
                "carrera_codigo",
                "area",
                "sede",
            ],
            COLUMNAS + ["rol"],
            COLUMNAS + ["area"],
        ]:
            r = self.importar([], antiguas)
            self.assertEqual(r.status_code, 400)
            self.assertIn(
                "La plantilla cambió: descarga la nueva desde el panel", str(r.data)
            )

    def test_admin_alta_director_coordinador_y_cero_correos(self):
        for datos in [
            self.funcionario(),
            self.funcionario(
                email="nuevo-director@inacap.cl",
                rol="DIRECTOR",
                carrera=None,
                area=self.area.pk,
            ),
        ]:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post("/api/admin/funcionarios/", datos, format="json")
            self.assertEqual(r.status_code, 201, r.data)
            self.assertIsNone(r.data["cuenta"])
            self.assertEqual(
                r.data["autorizado"]["nombre_completo"], datos["nombre_completo"]
            )
            self.assertIn("Solicitar acceso", r.data["siguiente_paso"])
        self.assertEqual(len(mail.outbox), 0)

    def test_permisos_funcionarios_y_dominio(self):
        self.client.force_authenticate(self.director)
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/", self.funcionario()
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/",
                self.funcionario(
                    email="otra-area@inacap.cl", carrera=self.otra_carrera.pk
                ),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/",
                self.funcionario(email="otra-sede@inacap.cl", sede=self.otra_sede.pk),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/",
                self.funcionario(
                    email="director2@inacap.cl",
                    rol="DIRECTOR",
                    carrera=None,
                    area=self.area.pk,
                ),
                format="json",
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.coord)
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/", self.funcionario()
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/", self.funcionario(email="mal@inacapmail.cl")
            ).status_code,
            400,
        )

    def test_no_reasignar_funcionario_fuera_del_ambito(self):
        UsuarioAutorizado.objects.create(
            email="ajeno@inacap.cl",
            nombre_completo="Ajeno",
            rol="COORDINADOR",
            carrera=self.otra_carrera,
            sede=self.sede,
        )
        self.client.force_authenticate(self.director)
        self.assertEqual(
            self.client.post(
                "/api/admin/funcionarios/", self.funcionario(email="ajeno@inacap.cl")
            ).status_code,
            403,
        )

    def test_alta_con_cuenta_aprueba_pero_exige_correo(self):
        for i, verificada in enumerate([True, False]):
            u = self.cuenta_pendiente(f"cuenta{i}@inacap.cl", verificada)
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(
                    "/api/admin/funcionarios/", self.funcionario(email=u.email)
                )
            self.assertEqual(r.status_code, 201, r.data)
            u.refresh_from_db()
            self.assertEqual(
                u.estado_cuenta, "ACTIVA" if verificada else "PENDIENTE_VERIFICACION"
            )
            self.assertEqual(u.solicitud.estado, "APROBADA")
        self.assertEqual(len(mail.outbox), 0)

    def test_alta_sin_cuenta_registro_preaprobado_tiene_prioridad(self):
        email = "director-preaprobado@inacap.cl"
        r = self.client.post(
            "/api/admin/funcionarios/",
            self.funcionario(
                email=email, rol="DIRECTOR", carrera=None, area=self.area.pk
            ),
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(mail.outbox), 0)
        self.client.force_authenticate(None)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                "/api/auth/registro/",
                {
                    "email": email,
                    "nombre_completo": "Registro",
                    "rut": "12345678-5",
                    "password": CLAVE,
                    "password2": CLAVE,
                    "rol_solicitado": "COORDINADOR",
                    "carrera": self.otra_carrera.pk,
                    "sede": self.otra_sede.pk,
                },
            )
        self.assertEqual(r.status_code, 201, r.data)
        u = Usuario.objects.get(email=email)
        self.assertEqual(u.rol, "DIRECTOR")
        self.assertIsNone(u.carrera)
        self.assertEqual(u.area, self.area)
        self.assertEqual(u.sede, self.sede)
        r = self.client.post(
            "/api/auth/verificar-correo/", {"token": token_verificacion(u)}
        )
        self.assertEqual(r.data["estado"], "ACTIVA")
        self.assertEqual(len(mail.outbox), 1)

    def test_cambiar_rol_activa_revoca_refresh(self):
        u = crear_usuario_activo(
            "ascenso@inacap.cl",
            CLAVE,
            nombre_completo="Activo",
            rol=Rol.COORDINADOR,
            carrera=self.carrera,
            sede=self.sede,
        )
        token = RefreshToken.for_user(u)
        r = self.client.post(
            "/api/admin/funcionarios/",
            self.funcionario(
                email=u.email, rol="DIRECTOR", carrera=None, area=self.area.pk
            ),
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        u.refresh_from_db()
        self.assertEqual(u.rol, "DIRECTOR")
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
        )
        self.client.force_authenticate(None)
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = str(token)
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            ).status_code,
            401,
        )

    def test_patch_y_filtro_tipo_con_estado_cuenta(self):
        alumno = UsuarioAutorizado.objects.create(
            email="alumno@inacapmail.cl",
            nombre_completo="Alumno",
            carrera=self.carrera,
            sede=self.sede,
        )
        self.client.force_authenticate(self.coord)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{alumno.pk}/", {"rol": "COORDINADOR"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{alumno.pk}/", {"nombre_completo": "No"}
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{alumno.pk}/", {"rol": "COORDINADOR"}
            ).status_code,
            400,
        )
        self.client.post(
            "/api/admin/funcionarios/", self.funcionario(email=self.coord.email)
        )
        r = self.client.get("/api/admin/autorizados/?tipo=estudiantes")
        self.assertEqual(r.data["count"], 1)
        self.assertIsNone(r.data["results"][0]["estado_cuenta"])
        r = self.client.get("/api/admin/autorizados/?tipo=funcionarios")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["estado_cuenta"], "ACTIVA")
        self.client.force_authenticate(self.director)
        autorizado = UsuarioAutorizado.objects.get(email=self.coord.email)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{autorizado.pk}/", {"carrera": self.ap.pk}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{autorizado.pk}/",
                {"carrera": self.otra_carrera.pk},
            ).status_code,
            403,
        )

    def test_patch_cambio_rol_revoca_y_estado_refleja_activacion(self):
        u = crear_usuario_activo(
            "patch@inacap.cl",
            CLAVE,
            nombre_completo="Para editar",
            rol=Rol.COORDINADOR,
            carrera=self.carrera,
            area=self.area,
            sede=self.sede,
        )
        autorizado = UsuarioAutorizado.objects.create(
            email=u.email,
            nombre_completo=u.nombre_completo,
            rol=u.rol,
            carrera=u.carrera,
            area=self.area,
            sede=self.sede,
        )
        token = RefreshToken.for_user(u)
        r = self.client.patch(
            f"/api/admin/autorizados/{autorizado.pk}/",
            {"rol": "DIRECTOR", "area": self.area.pk},
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
        )
        u.refresh_from_db()
        self.assertEqual(u.rol, "DIRECTOR")
        self.assertIsNone(u.carrera)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{autorizado.pk}/", {"activo": False}
            ).data["estado_cuenta"],
            "DESACTIVADA",
        )
        self.assertEqual(
            self.client.patch(
                f"/api/admin/autorizados/{autorizado.pk}/", {"activo": True}
            ).data["estado_cuenta"],
            "ACTIVA",
        )

    @override_settings(PREAPROBACION_LISTA_BLANCA=False)
    def test_director_preasignado_con_area_puede_aprobarse_con_revision(self):
        email = "revision-director@inacap.cl"
        r = self.client.post(
            "/api/admin/funcionarios/",
            self.funcionario(
                email=email, rol="DIRECTOR", carrera=None, area=self.area.pk
            ),
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.client.force_authenticate(None)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                "/api/auth/registro/",
                {
                    "email": email,
                    "nombre_completo": "Funcionario",
                    "rut": "12345678-5",
                    "password": CLAVE,
                    "password2": CLAVE,
                    "rol_solicitado": "COORDINADOR",
                    "carrera": self.otra_carrera.pk,
                    "sede": self.otra_sede.pk,
                },
            )
        self.assertEqual(r.status_code, 201, r.data)
        u = Usuario.objects.get(email=email)
        self.assertEqual(
            self.client.post(
                "/api/auth/verificar-correo/", {"token": token_verificacion(u)}
            ).data["estado"],
            "PENDIENTE_APROBACION",
        )
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/solicitudes/{u.solicitud.pk}/aprobar/")
        self.assertEqual(r.status_code, 200, r.data)
        u.refresh_from_db()
        self.assertEqual(u.area, self.area)
