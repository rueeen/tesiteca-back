from io import BytesIO
from decouple import config
from django.core.management.base import BaseCommand, CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from reportlab.pdfgen import canvas
from academico.models import Sede, Area, Carrera
from usuarios.models import Usuario, UsuarioAutorizado, Rol
from usuarios.serializers import CorreoSerializer
from tesis.models import Tesis, Estado
from tesis.servicios import guardar_tesis


class Command(BaseCommand):
    help = "Carga los catálogos y, opcionalmente, 15 tesis ficticias de demostración"

    def add_arguments(self, parser):
        parser.add_argument("--con-ejemplos", action="store_true")
        parser.add_argument(
            "--reset-ejemplos",
            action="store_true",
            help="Borra las tesis Demo y sus archivos antes de regenerarlas",
        )

    def handle(self, *args, **opciones):
        sede, _ = Sede.objects.get_or_create(
            nombre="Arica", defaults={"ciudad": "Arica", "region": "XV", "orden": 1}
        )
        area, _ = Area.objects.get_or_create(
            nombre="Informática, Ciberseguridad y Telecomunicaciones"
        )
        carreras = []
        for codigo, nombre in [
            ("IEI", "Ingeniería en Informática"),
            ("AP", "Analista Programador"),
        ]:
            carrera, _ = Carrera.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "area": area,
                    "permite_repositorio": True,
                    "nivel_formacion": "INGENIERIA" if codigo == "IEI" else "TECNICO",
                    "duracion_semestres": 8 if codigo == "IEI" else 4,
                },
            )
            carreras.append(carrera)
        email = config("SEED_ADMIN_EMAIL", default="").strip().lower()
        if email:
            serial = CorreoSerializer(data={"email": email})
            if not serial.is_valid():
                raise CommandError(
                    "SEED_ADMIN_EMAIL debe ser un correo institucional válido"
                )
            UsuarioAutorizado.objects.update_or_create(
                email=email,
                defaults={
                    "nombre_completo": "Administrador demo",
                    "rol": Rol.ADMIN,
                    "sede": sede,
                    "activo": True,
                },
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "SEED_ADMIN_EMAIL no configurado: no se agregó administrador a la lista blanca"
                )
            )
        if opciones["con_ejemplos"] or opciones["reset_ejemplos"]:
            if opciones["reset_ejemplos"]:
                self.reset_ejemplos()
            self.crear_ejemplos(sede, area, carreras)
        self.stdout.write(self.style.SUCCESS("Seed completado"))

    def reset_ejemplos(self):
        ejemplos = Tesis.objects.filter(titulo__startswith="Demo ").prefetch_related(
            "materiales"
        )
        archivos = []
        for tesis in ejemplos:
            archivos.extend([tesis.pdf_original, tesis.pdf_marcado])
            archivos.extend(m.archivo for m in tesis.materiales.all() if m.archivo)
        with transaction.atomic():
            ejemplos.delete()

            def limpiar():
                for archivo in archivos:
                    if archivo.name:
                        archivo.storage.delete(archivo.name)

            transaction.on_commit(limpiar, robust=True)

    # AP: confirmar duración con la malla vigente.
    def crear_ejemplos(self, sede, area, carreras):
        iei, ap = carreras
        configuracion = [
            (Rol.ESTUDIANTE, iei),
            (Rol.ESTUDIANTE, iei),
            (Rol.ESTUDIANTE, ap),
            (Rol.COORDINADOR, ap),
            (Rol.COORDINADOR, iei),
            (Rol.DIRECTOR, None),
        ]
        personas = []
        for numero, (rol, carrera) in enumerate(configuracion, 1):
            correo = f"demo{numero}@inacapmail.cl"
            datos = {
                "nombre_completo": f"Persona ficticia {numero}",
                "rol": rol,
                "carrera": carrera,
                "area": area if rol == Rol.DIRECTOR else None,
                "sede": sede,
            }
            UsuarioAutorizado.objects.update_or_create(
                email=correo, defaults={**datos, "activo": True}
            )
            usuario, creado = Usuario.objects.update_or_create(
                email=correo, defaults=datos
            )
            from django.utils import timezone
            from usuarios.models import EstadoCuenta

            usuario.estado_cuenta = EstadoCuenta.ACTIVA
            usuario.email_verificado_en = usuario.email_verificado_en or timezone.now()
            if creado:
                usuario.set_unusable_password()
            usuario.save()
            personas.append(usuario)

        for i in range(15):
            titulo = f"Demo {i+1:02d}: Biblioteca tecnológica de Arica"
            if Tesis.objects.filter(titulo=titulo).exists():
                continue
            carrera = carreras[i % 2]
            estudiantes = personas[:2] if carrera == iei else [personas[2]]
            coordinador = personas[4] if carrera == iei else personas[3]
            estado = (
                Estado.PUBLICADA
                if i < 11
                else Estado.EN_REVISION if i < 14 else Estado.RECHAZADA
            )
            usuario = coordinador if estado == Estado.PUBLICADA else estudiantes[0]
            salida = BytesIO()
            pdf = canvas.Canvas(salida)
            for pagina in range(5 + i % 6):
                pdf.drawString(50, 780, titulo)
                pdf.drawString(
                    50,
                    750,
                    f"Contenido ficticio académico. Página {pagina+1}. Proyecto {i+1}.",
                )
                pdf.showPage()
            pdf.save()
            datos = {
                "titulo": titulo,
                "resumen": f"Proyecto demostrativo de informática {i+1}: desarrollo de soluciones para Arica.",
                "palabras_clave": [
                    "seguridad,redes",
                    "software,datos",
                    "web,educación",
                ][i % 3],
                "tipo": "PROYECTO_TITULO",
                "anio": 2021 + i % 6,
                "periodo": 1 + i % 2,
                "carrera": carrera,
                "sede": sede,
                "profesor_guia": ["Ana Pérez", "Luis Soto", "María Rojas"][i % 3],
                "autores": [
                    {
                        "nombre_completo": estudiante.nombre_completo,
                        "email": estudiante.email,
                    }
                    for estudiante in estudiantes
                ],
                "pdf": SimpleUploadedFile(
                    "demo.pdf", salida.getvalue(), content_type="application/pdf"
                ),
                "publicar": estado == Estado.PUBLICADA,
            }
            if i % 3 == 0:
                datos["repositorio_url"] = (
                    f"https://github.com/ejemplo-ficticio/tesis-demo-{i+1}"
                )
            tesis = guardar_tesis(datos, usuario)
            for estudiante in estudiantes:
                tesis.autores.filter(email=estudiante.email).update(usuario=estudiante)
            if estado == Estado.RECHAZADA:
                tesis.estado = estado
                tesis.observacion_revision = (
                    "Completar las referencias bibliográficas antes de reenviar."
                )
                tesis.revisado_por = coordinador
                tesis.save(
                    update_fields=["estado", "observacion_revision", "revisado_por"]
                )

        self.stdout.write("Correo                         | Rol          | Carrera")
        for usuario in personas:
            self.stdout.write(
                f'{usuario.email:<30} | {usuario.rol:<12} | {usuario.carrera.codigo if usuario.carrera else "Área completa"}'
            )
