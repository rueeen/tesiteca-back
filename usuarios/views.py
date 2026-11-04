import csv
import io
from openpyxl import Workbook, load_workbook
from django.conf import settings
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework.permissions import BasePermission
from .cookies import poner_refresh, borrar_refresh
from django.db import transaction
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from config.throttling import ThrottleIP
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from academico.models import Carrera, Area, Sede
from .models import UsuarioAutorizado, Usuario, ImportacionLote, Rol, EstadoCuenta
from .serializers import (
    UsuarioSerializer,
    AutorizadoSerializer,
)
from .permisos import GestionaAutorizados, puede_administrar
from .cuentas import puede_iniciar_sesion


def error_legible(detalle, campo=""):
    if isinstance(detalle, dict):
        return "; ".join(
            error_legible(valor, clave if clave != "non_field_errors" else "")
            for clave, valor in detalle.items()
        )
    if isinstance(detalle, (list, tuple)):
        mensajes = "; ".join(error_legible(valor) for valor in detalle)
    else:
        mensajes = str(detalle)
    return f"{campo}: {mensajes}" if campo else mensajes


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
            "carrera__area", "area", "sede"
        ).order_by("email")
        u = self.request.user
        if u.rol == Rol.ADMIN:
            return qs
        if u.rol == Rol.COORDINADOR and u.carrera_id:
            return qs.filter(carrera=u.carrera, sede=u.sede, rol=Rol.ESTUDIANTE)
        if u.rol == Rol.DIRECTOR and u.area_id:
            return qs.filter(
                carrera__area=u.area,
                sede=u.sede,
                rol__in=[Rol.ESTUDIANTE, Rol.COORDINADOR],
            )
        return qs.none()

    def perform_create(self, serializer):
        if not puede_administrar(self.request.user, serializer.validated_data):
            raise PermissionDenied()
        serializer.save()

    def perform_update(self, serializer):
        datos = {
            c: serializer.validated_data.get(c, getattr(serializer.instance, c))
            for c in ["rol", "carrera", "sede"]
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
            if not filas or list(filas[0]) not in (COLUMNAS, COLUMNAS + ["activo"]):
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
                    for k, v in zip(filas[0], fila)
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
                from academico.normalizacion import normalizar_nombre

                sede = next(
                    (
                        s
                        for s in Sede.objects.all()
                        if normalizar_nombre(s.nombre)
                        == normalizar_nombre(datos.get("sede", ""))
                    ),
                    None,
                )
                if datos.get("sede") and not sede:
                    raise ValueError("La sede no existe")
                contenido = {
                    k: datos.get(k, "")
                    for k in ["email", "rut", "nombre_completo", "rol"]
                }
                contenido.update(
                    carrera=carrera.pk if carrera else None,
                    area=area.pk if area else None,
                    sede=sede.pk if sede else None,
                )
                if "activo" in datos:
                    valores_activo = {
                        "true": True,
                        "false": False,
                        "1": True,
                        "0": False,
                        "sí": True,
                        "si": True,
                        "no": False,
                    }
                    if datos["activo"].lower() not in valores_activo:
                        raise ValueError("activo debe ser true/false, 1/0 o sí/no")
                    contenido["activo"] = valores_activo[datos["activo"].lower()]
                existente = UsuarioAutorizado.objects.filter(
                    email=contenido["email"].lower()
                ).first()
                if existente and not puede_administrar(
                    request.user,
                    {
                        "rol": existente.rol,
                        "carrera": existente.carrera,
                        "sede": existente.sede,
                    },
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
                lote.errores.append(
                    {
                        "fila": numero,
                        "motivo": (
                            error_legible(exc.detail)
                            if isinstance(exc, ValidationError)
                            else str(exc)
                        ),
                    }
                )
        lote.save()
        return Response(
            {
                c: getattr(lote, c)
                for c in ["total_filas", "creados", "actualizados", "errores"]
            }
        )


class ProteccionCookie(BasePermission):
    message = "Solicitud de sesión no permitida"

    def has_permission(self, request, view):
        origen = request.headers.get("Origin")
        return request.headers.get("X-Requested-With") == "XMLHttpRequest" and (
            origen is None or origen in settings.CSRF_TRUSTED_ORIGINS
        )


class SesionCookie(APIView):
    authentication_classes = (
        []
    )  # Permitir renovar/cerrar aunque el access esté vencido.
    permission_classes = [AllowAny, ProteccionCookie]
    throttle_classes = [ThrottleIP]
    throttle_scope = "refresh"


class RenovarSesion(SesionCookie):
    def post(self, request):
        valor = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if valor is None:
            return Response(status=204)
        try:
            with transaction.atomic():
                token = RefreshToken(valor)
                usuario = (
                    Usuario.objects.select_related("carrera", "area", "sede")
                    .filter(pk=token["user_id"])
                    .first()
                )
                if not puede_iniciar_sesion(usuario):
                    token.blacklist()
                    return borrar_refresh(
                        Response({"detail": "Sesión no autorizada"}, status=401)
                    )
                serial = TokenRefreshSerializer(data={"refresh": valor})
                serial.is_valid(raise_exception=True)
                datos = serial.validated_data
                return poner_refresh(
                    Response(
                        {
                            "access": datos["access"],
                            "usuario": UsuarioSerializer(usuario).data,
                        }
                    ),
                    datos["refresh"],
                )
        except (TokenError, InvalidToken):
            return borrar_refresh(
                Response({"detail": "Sesión inválida o vencida"}, status=401)
            )


class CerrarSesion(SesionCookie):
    def post(self, request):
        valor = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if valor:
            try:
                RefreshToken(valor).blacklist()
            except TokenError:
                pass
        return borrar_refresh(Response(status=204))
