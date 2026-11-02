import ipaddress
from pathlib import Path
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from usuarios.models import Rol
from .models import Tesis, MaterialAdicional, RegistroAcceso, Estado
from .serializers import (
    TesisListaSerializer,
    TesisDetalleSerializer,
    TesisEscrituraSerializer,
    MaterialSerializer,
)
from .permisos import visibles, revisa, edita, material_visible, PermisoTesis
from .filtros import FiltroTesis
from .marca_agua import aplicar_marca_lector


def ip_cliente(request):
    # No confiar en X-Forwarded-For enviado por el cliente.
    try:
        return str(ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")))
    except ValueError:
        return None


def registrar(request, tesis, accion):
    RegistroAcceso.objects.create(
        usuario=request.user,
        tesis=tesis,
        accion=accion,
        ip=ip_cliente(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )


def respuesta_archivo(archivo, nombre, pdf=False):
    respuesta = FileResponse(
        archivo,
        content_type="application/pdf" if pdf else "application/octet-stream",
        as_attachment=not pdf,
        filename=nombre,
    )
    respuesta["Cache-Control"] = "no-store"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


class TesisViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermisoTesis]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = FiltroTesis
    ordering_fields = ["anio", "titulo", "fecha_publicacion"]
    ordering = ["-fecha_publicacion"]

    def get_queryset(self):
        qs = visibles(
            Tesis.objects.select_related(
                "carrera", "sede", "subido_por"
            ).prefetch_related("autores", "materiales"),
            self.request.user,
        )
        if self.action == "list":
            qs = qs.filter(estado=Estado.PUBLICADA)
        return qs

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        texto = self.request.query_params.get("search", "").strip()
        if texto:
            filtro = (
                Q(titulo__icontains=texto)
                | Q(resumen__icontains=texto)
                | Q(palabras_clave__icontains=texto)
                | Q(autores__nombre_completo__icontains=texto)
                | Q(profesor_guia__icontains=texto)
            )
            if self.request.query_params.get("en_contenido", "").lower() == "true":
                filtro |= Q(texto_extraido__icontains=texto)
            qs = qs.filter(filtro).distinct()
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return TesisListaSerializer
        if self.action in ["create", "partial_update", "update"]:
            return TesisEscrituraSerializer
        return TesisDetalleSerializer

    def create(self, request, *args, **kwargs):
        serial = self.get_serializer(data=request.data)
        serial.is_valid(raise_exception=True)
        tesis = serial.save()
        return Response(
            TesisDetalleSerializer(tesis, context=self.get_serializer_context()).data,
            status=201,
        )

    def partial_update(self, request, *args, **kwargs):
        serial = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serial.is_valid(raise_exception=True)
        tesis = serial.save()
        return Response(
            TesisDetalleSerializer(tesis, context=self.get_serializer_context()).data
        )

    def perform_destroy(self, instance):
        archivos = [instance.pdf_original, instance.pdf_marcado] + [
            m.archivo for m in instance.materiales.all() if m.archivo
        ]
        with transaction.atomic():
            instance.delete()
            transaction.on_commit(
                lambda: [f.storage.delete(f.name) for f in archivos if f.name]
            )

    @action(detail=False, methods=["get"], url_path="mis-tesis")
    def mis_tesis(self, request):
        qs = self.filter_queryset(
            self.get_queryset()
            .filter(Q(subido_por=request.user) | Q(autores__usuario=request.user))
            .distinct()
        )
        pagina = self.paginate_queryset(qs)
        return self.get_paginated_response(
            TesisDetalleSerializer(
                pagina, many=True, context=self.get_serializer_context()
            ).data
        )

    @action(detail=False, methods=["get"])
    def pendientes(self, request):
        u = request.user
        if u.rol == Rol.ESTUDIANTE:
            raise PermissionDenied()
        qs = self.get_queryset().filter(estado=Estado.EN_REVISION)
        if u.rol == Rol.COORDINADOR:
            qs = qs.filter(carrera_id=u.carrera_id) if u.carrera_id else qs.none()
        elif u.rol == Rol.DIRECTOR:
            qs = qs.filter(carrera__area_id=u.area_id) if u.area_id else qs.none()
        elif u.rol != Rol.ADMIN:
            raise PermissionDenied()
        pagina = self.paginate_queryset(self.filter_queryset(qs))
        return self.get_paginated_response(
            TesisDetalleSerializer(
                pagina, many=True, context=self.get_serializer_context()
            ).data
        )

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        tesis = self.get_object()
        with tesis.pdf_marcado.open("rb") as archivo:
            salida = aplicar_marca_lector(archivo, request.user, ip_cliente(request))
        registrar(request, tesis, "VER_PDF")
        return respuesta_archivo(salida, f"tesis-{tesis.id}.pdf", True)

    @action(detail=True, methods=["get"], url_path="pdf-original")
    def original(self, request, pk=None):
        if request.user.rol != Rol.ADMIN:
            raise PermissionDenied()
        tesis = self.get_object()
        registrar(request, tesis, "VER_PDF")
        return respuesta_archivo(
            tesis.pdf_original.open("rb"), f"original-{tesis.id}.pdf", True
        )

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        tesis = self.get_object()
        if not revisa(request.user, tesis):
            raise PermissionDenied()
        if tesis.estado != Estado.EN_REVISION:
            raise ValidationError("La tesis debe estar en revisión")
        tesis.estado = Estado.PUBLICADA
        tesis.fecha_publicacion = timezone.now()
        tesis.revisado_por = request.user
        tesis.observacion_revision = ""
        tesis.save()
        return Response(
            TesisDetalleSerializer(tesis, context=self.get_serializer_context()).data
        )

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        tesis = self.get_object()
        if not revisa(request.user, tesis):
            raise PermissionDenied()
        observacion = request.data.get("observacion", "")
        if not isinstance(observacion, str) or not observacion.strip():
            raise ValidationError("La observación es obligatoria")
        if tesis.estado != Estado.EN_REVISION:
            raise ValidationError("La tesis debe estar en revisión")
        tesis.estado = Estado.RECHAZADA
        tesis.observacion_revision = observacion.strip()
        tesis.revisado_por = request.user
        tesis.save()
        return Response({"estado": tesis.estado})

    @action(detail=True, methods=["post"])
    def reenviar(self, request, pk=None):
        tesis = self.get_object()
        autor = (
            tesis.subido_por_id == request.user.pk
            or tesis.autores.filter(usuario=request.user).exists()
        )
        if not autor:
            raise PermissionDenied()
        if tesis.estado not in (Estado.BORRADOR, Estado.RECHAZADA):
            raise ValidationError("La tesis no se puede reenviar")
        tesis.estado = Estado.EN_REVISION
        tesis.observacion_revision = ""
        tesis.revisado_por = None
        tesis.fecha_publicacion = None
        tesis.save()
        return Response({"estado": tesis.estado})

    @action(detail=True, methods=["get", "post"])
    def materiales(self, request, pk=None):
        tesis = self.get_object()
        contexto = {**self.get_serializer_context(), "tesis": tesis}
        if request.method == "GET":
            return Response(
                MaterialSerializer(
                    tesis.materiales.all(), many=True, context=contexto
                ).data
            )
        serial = MaterialSerializer(data=request.data, context=contexto)
        serial.is_valid(raise_exception=True)
        serial.save(tesis=tesis)
        return Response(serial.data, status=201)


class MaterialViewSet(viewsets.GenericViewSet):
    http_method_names = ["post", "get", "delete", "head", "options"]

    def get_queryset(self):
        return MaterialAdicional.objects.select_related("tesis__carrera").filter(
            tesis__in=visibles(Tesis.objects.all(), self.request.user)
        )

    def destroy(self, request, pk=None):
        material = self.get_object()
        if not edita(request.user, material.tesis):
            raise PermissionDenied()
        archivo = material.archivo
        material.delete()
        if archivo:
            archivo.storage.delete(archivo.name)
        return Response(status=204)

    def permitido(self, request):
        material = self.get_object()
        if not material_visible(request.user, material):
            raise PermissionDenied()
        return material

    @action(detail=True, methods=["post"])
    def acceso(self, request, pk=None):
        material = self.permitido(request)
        if material.tipo not in ["REPOSITORIO", "ENLACE"]:
            raise ValidationError("El material no es un enlace")
        registrar(request, material.tesis, "VER_REPOSITORIO")
        return Response({"url": material.url})

    @action(detail=True, methods=["get"])
    def descargar(self, request, pk=None):
        material = self.permitido(request)
        if material.tipo != "ARCHIVO" or not material.archivo:
            raise ValidationError("El material no tiene archivo")
        registrar(request, material.tesis, "DESCARGAR_MATERIAL")
        return respuesta_archivo(
            material.archivo.open("rb"),
            f"material-{material.id}{Path(material.archivo.name).suffix}",
        )
