import csv
import io
import secrets
import logging
from datetime import timedelta
from openpyxl import Workbook, load_workbook
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from academico.models import Carrera, Area, Sede
from .models import CodigoAcceso, UsuarioAutorizado, Usuario, ImportacionLote, Rol
from .serializers import (
    CorreoSerializer,
    CodigoSerializer,
    UsuarioSerializer,
    AutorizadoSerializer,
)
from .permisos import GestionaAutorizados, puede_administrar

MENSAJE = "Si el correo está autorizado, recibirás un código"


class SolicitarCodigo(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "codigo"

    def post(self, request):
        entrada = CorreoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        email = entrada.validated_data["email"]
        ahora = timezone.now()
        with transaction.atomic():
            solicitudes = CodigoAcceso.objects.filter(
                email=email, creado__gte=ahora - timedelta(minutes=10)
            )
            if solicitudes.count() >= 3:
                return Response(
                    {"detail": "Intenta nuevamente en 10 minutos"}, status=429
                )
            CodigoAcceso.objects.filter(email=email, usado=False).update(usado=True)
            autorizado = UsuarioAutorizado.objects.filter(
                email=email, activo=True
            ).exists()
            codigo = f"{secrets.randbelow(1000000):06d}"
            # También contar solicitudes no autorizadas evita revelar la lista blanca por el límite.
            CodigoAcceso.objects.create(
                email=email,
                codigo_hash=make_password(codigo),
                expira_en=ahora + timedelta(minutes=10),
                usado=not autorizado,
            )
            if autorizado:
                try:
                    send_mail(
                        "Código de acceso a Biblioteca de Tesis",
                        f"Tu código es {codigo}. Expira en 10 minutos.",
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                    )
                except Exception:
                    # No revelar la lista blanca si el transporte de correo falla.
                    logging.getLogger(__name__).error(
                        "No se pudo enviar un código de acceso"
                    )
        return Response({"detail": MENSAJE})


class VerificarCodigo(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "codigo"

    def post(self, request):
        entrada = CodigoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        email = entrada.validated_data["email"]
        with transaction.atomic():
            codigo = (
                CodigoAcceso.objects.select_for_update()
                .filter(
                    email=email,
                    usado=False,
                    expira_en__gt=timezone.now(),
                    intentos__lt=5,
                )
                .order_by("-creado")
                .first()
            )
            autorizado = UsuarioAutorizado.objects.filter(
                email=email, activo=True
            ).first()
            if not codigo or not autorizado:
                return Response({"detail": "Código inválido o vencido"}, status=400)
            codigo.intentos += 1
            valido = check_password(
                entrada.validated_data["codigo"], codigo.codigo_hash
            )
            codigo.usado = valido or codigo.intentos >= 5
            codigo.save(update_fields=["intentos", "usado"])
            if not valido:
                return Response({"detail": "Código inválido o vencido"}, status=400)
            datos = {
                campo: getattr(autorizado, campo)
                for campo in [
                    "rut",
                    "nombre_completo",
                    "rol",
                    "carrera",
                    "area",
                    "sede",
                ]
            }
            usuario, creado = Usuario.objects.get_or_create(email=email, defaults=datos)
            if not usuario.is_active:
                return Response({"detail": "Usuario desactivado"}, status=400)
            for campo, valor in datos.items():
                setattr(usuario, campo, valor)
            if creado:
                usuario.set_unusable_password()
            usuario.save()
            token = RefreshToken.for_user(usuario)
        return Response(
            {
                "access": str(token.access_token),
                "refresh": str(token),
                "usuario": UsuarioSerializer(usuario).data,
            }
        )


class MiUsuario(APIView):
    def get(self, request):
        return Response(UsuarioSerializer(request.user).data)


COLUMNAS = ["email", "rut", "nombre_completo", "rol", "carrera_codigo", "area", "sede"]


class AutorizadosViewSet(viewsets.ModelViewSet):
    serializer_class = AutorizadoSerializer
    permission_classes = [GestionaAutorizados]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["email", "nombre_completo", "rut"]
    filterset_fields = ["rol", "carrera", "activo"]
    ordering = ["email"]

    def get_queryset(self):
        qs = UsuarioAutorizado.objects.select_related(
            "carrera", "area", "sede"
        ).order_by("email")
        u = self.request.user
        if u.rol == Rol.ADMIN:
            return qs
        if u.rol == Rol.COORDINADOR and u.carrera_id:
            return qs.filter(carrera=u.carrera, rol=Rol.ESTUDIANTE)
        if u.rol == Rol.DIRECTOR and u.area_id:
            return qs.filter(
                carrera__area=u.area, rol__in=[Rol.ESTUDIANTE, Rol.COORDINADOR]
            )
        return qs.none()

    def perform_create(self, serializer):
        if not puede_administrar(self.request.user, serializer.validated_data):
            raise PermissionDenied()
        serializer.save()

    def perform_update(self, serializer):
        datos = {
            c: serializer.validated_data.get(c, getattr(serializer.instance, c))
            for c in ["rol", "carrera"]
        }
        if not puede_administrar(self.request.user, datos):
            raise PermissionDenied()
        serializer.save()

    @action(detail=False, methods=["get"])
    def plantilla(self, request):
        libro = Workbook()
        libro.active.append(COLUMNAS)
        salida = io.BytesIO()
        libro.save(salida)
        respuesta = HttpResponse(
            salida.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        respuesta["Content-Disposition"] = 'attachment; filename="autorizados.xlsx"'
        return respuesta

    @action(detail=False, methods=["post"])
    def importar(self, request):
        archivo = request.FILES.get("archivo")
        if not archivo or archivo.size > 5 * 1024 * 1024:
            raise ValidationError("Adjunta un archivo CSV o XLSX de hasta 5 MB")
        try:
            if archivo.name.lower().endswith(".csv"):
                filas = list(
                    csv.reader(io.StringIO(archivo.read().decode("utf-8-sig")))
                )
            elif archivo.name.lower().endswith(".xlsx"):
                libro = load_workbook(archivo, read_only=True, data_only=True)
                filas = list(libro.active.iter_rows(values_only=True))
                libro.close()
            else:
                raise ValueError("Formato no admitido")
            if not filas or list(filas[0]) != COLUMNAS:
                raise ValueError("Las columnas deben coincidir con la plantilla")
            if len(filas) > 10001:
                raise ValueError("Máximo 10000 filas por importación")
        except Exception as exc:
            raise ValidationError(f"Archivo inválido: {exc}")
        archivo.seek(0)
        lote = ImportacionLote.objects.create(archivo=archivo, creado_por=request.user)
        for numero, fila in enumerate(filas[1:], 2):
            if not any(v is not None and str(v).strip() for v in fila):
                continue
            lote.total_filas += 1
            try:
                datos = {
                    k: str(v).strip() if v is not None else ""
                    for k, v in zip(COLUMNAS, fila)
                }
                carrera = (
                    Carrera.objects.get(codigo=datos["carrera_codigo"])
                    if datos.get("carrera_codigo")
                    else None
                )
                area = (
                    Area.objects.get(nombre=datos["area"])
                    if datos.get("area")
                    else None
                )
                sede = (
                    Sede.objects.get(nombre=datos["sede"])
                    if datos.get("sede")
                    else None
                )
                contenido = {
                    k: datos.get(k, "")
                    for k in ["email", "rut", "nombre_completo", "rol"]
                }
                contenido.update(
                    carrera=carrera.pk if carrera else None,
                    area=area.pk if area else None,
                    sede=sede.pk if sede else None,
                )
                existente = UsuarioAutorizado.objects.filter(
                    email=contenido["email"].lower()
                ).first()
                if existente and not puede_administrar(
                    request.user, {"rol": existente.rol, "carrera": existente.carrera}
                ):
                    raise ValueError("No puedes modificar este autorizado")
                serial = AutorizadoSerializer(existente, data=contenido)
                serial.is_valid(raise_exception=True)
                if not puede_administrar(request.user, serial.validated_data):
                    raise ValueError("Fila fuera de tu ámbito de permisos")
                with transaction.atomic():
                    serial.save(lote=lote)
                if existente:
                    lote.actualizados += 1
                else:
                    lote.creados += 1
            except Exception as exc:
                lote.errores.append({"fila": numero, "motivo": str(exc)})
        lote.save()
        return Response(
            {
                c: getattr(lote, c)
                for c in ["total_filas", "creados", "actualizados", "errores"]
            }
        )
