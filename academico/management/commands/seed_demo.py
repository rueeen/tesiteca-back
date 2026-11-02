from io import BytesIO
from decouple import config
from django.core.management.base import BaseCommand, CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.validators import validate_email
from reportlab.pdfgen import canvas
from academico.models import Sede, Area, Carrera
from usuarios.models import Usuario, UsuarioAutorizado, Rol
from usuarios.serializers import CorreoSerializer
from tesis.models import Tesis
from tesis.servicios import guardar_tesis


class Command(BaseCommand):
    help = "Carga los catálogos y, opcionalmente, 15 tesis ficticias de demostración"

    def add_arguments(self, parser):
        parser.add_argument("--con-ejemplos", action="store_true")

    def handle(self, *args, **opciones):
        sede, _ = Sede.objects.get_or_create(
            nombre="Arica", defaults={"ciudad": "Arica"}
        )
        area, _ = Area.objects.get_or_create(
            nombre="Informática, Ciberseguridad y Telecomunicaciones"
        )
        carreras = []
        for codigo, nombre in [
            ("IEI", "Ingeniería en Informática"),
            ("AP", "Analista Programador"),
        ]:
            carrera, _ = Carrera.objects.get_or_create(
                codigo=codigo,
                defaults={"nombre": nombre, "area": area, "permite_repositorio": True},
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
        if opciones["con_ejemplos"]:
            personas = []
            for i in range(4):
                carrera = carreras[i % 2]
                rol = Rol.COORDINADOR if i == 3 else Rol.ESTUDIANTE
                correo = f"demo{i+1}@inacapmail.cl"
                datos = {
                    "nombre_completo": f"Persona ficticia {i+1}",
                    "rol": rol,
                    "carrera": carrera,
                    "area": area,
                    "sede": sede,
                }
                UsuarioAutorizado.objects.get_or_create(email=correo, defaults=datos)
                usuario, creado = Usuario.objects.get_or_create(
                    email=correo, defaults=datos
                )
                if creado:
                    usuario.set_unusable_password()
                    usuario.save()
                personas.append(usuario)
            for i in range(15):
                titulo = f"Demo {i+1:02d}: Biblioteca tecnológica de Arica"
                if Tesis.objects.filter(titulo=titulo).exists():
                    continue
                carrera = carreras[i % 2]
                usuario = personas[3]
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
                    "semestre": 1 + i % 2,
                    "carrera": carrera,
                    "sede": sede,
                    "profesor_guia": ["Ana Pérez", "Luis Soto", "María Rojas"][i % 3],
                    "autores": [
                        {
                            "nombre_completo": personas[i % 3].nombre_completo,
                            "email": personas[i % 3].email,
                        }
                    ],
                    "pdf": SimpleUploadedFile(
                        "demo.pdf", salida.getvalue(), content_type="application/pdf"
                    ),
                    "publicar": True,
                }
                if i % 3 == 0:
                    datos["repositorio_url"] = (
                        f"https://github.com/ejemplo-ficticio/tesis-demo-{i+1}"
                    )
                tesis = guardar_tesis(datos, usuario)
                tesis.autores.filter(email=personas[i % 3].email).update(
                    usuario=personas[i % 3]
                )
        self.stdout.write(self.style.SUCCESS("Seed completado"))
