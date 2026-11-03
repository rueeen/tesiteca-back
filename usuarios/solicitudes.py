from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from academico.models import Carrera, Sede, Area
from .models import SolicitudAcceso, UsuarioAutorizado, Rol, EstadoCuenta
from .serializers import SolicitudSerializer
from .permisos import GestionaAutorizados
from .cuentas import aprobar_cuenta


class AprobacionSerializer(serializers.Serializer):
    rol = serializers.ChoiceField(choices=Rol.choices, required=False)
    carrera = serializers.PrimaryKeyRelatedField(
        queryset=Carrera.objects.filter(activa=True), required=False, allow_null=True
    )
    sede = serializers.PrimaryKeyRelatedField(
        queryset=Sede.objects.filter(activa=True), required=False
    )


class SolicitudesViewSet(viewsets.GenericViewSet):
    serializer_class = SolicitudSerializer
    permission_classes = [GestionaAutorizados]
    filterset_fields = ["estado", "carrera", "sede"]
    search_fields = ["usuario__email", "usuario__nombre_completo", "usuario__rut"]

    def get_queryset(self):
        qs = (
            SolicitudAcceso.objects.select_related(
                "usuario", "carrera", "sede", "revisada_por"
            )
            .filter(usuario__email_verificado_en__isnull=False)
            .filter(
                Q(usuario__estado_cuenta=EstadoCuenta.PENDIENTE_APROBACION)
                | Q(estado__in=["APROBADA", "RECHAZADA"])
            )
        )
        u = self.request.user
        if u.rol == Rol.ADMIN:
            return qs
        if not u.sede_id:
            return qs.none()
        qs = qs.filter(sede=u.sede)
        if u.rol == Rol.COORDINADOR and u.carrera_id:
            return qs.filter(rol_solicitado=Rol.ESTUDIANTE, carrera=u.carrera)
        if u.rol == Rol.DIRECTOR and u.area_id:
            return qs.filter(
                rol_solicitado__in=[Rol.ESTUDIANTE, Rol.COORDINADOR],
                carrera__area=u.area,
            )
        return qs.none()

    def list(self, request):
        pagina = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(pagina, many=True).data)

    @action(detail=False, methods=["get"])
    def resumen(self, request):
        return Response(
            {
                "pendientes": self.get_queryset()
                .filter(
                    estado="PENDIENTE",
                    usuario__estado_cuenta=EstadoCuenta.PENDIENTE_APROBACION,
                )
                .count()
            }
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def aprobar(self, request, pk=None):
        solicitud = self.get_object()
        if (
            solicitud.estado != "PENDIENTE"
            or solicitud.usuario.estado_cuenta != EstadoCuenta.PENDIENTE_APROBACION
        ):
            raise ValidationError("La solicitud no está pendiente")
        serial = AprobacionSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        cambios = serial.validated_data
        if request.user.rol != Rol.ADMIN and any(
            k in cambios
            and cambios[k] != getattr(solicitud, "rol_solicitado" if k == "rol" else k)
            for k in cambios
        ):
            raise PermissionDenied("Solo ADMIN puede modificar lo solicitado")
        datos = {
            "rol": cambios.get("rol", solicitud.rol_solicitado),
            "carrera": cambios.get("carrera", solicitud.carrera),
            "sede": cambios.get("sede", solicitud.sede),
        }
        if (
            solicitud.usuario.email.endswith("@inacapmail.cl")
            and datos["rol"] != Rol.ESTUDIANTE
        ):
            raise ValidationError(
                {"rol": "Los correos de estudiantes solo pueden tener rol ESTUDIANTE"}
            )
        if datos["rol"] in (Rol.ESTUDIANTE, Rol.COORDINADOR) and not datos["carrera"]:
            raise ValidationError({"carrera": "La carrera es obligatoria"})
        if (
            datos["rol"] == Rol.DIRECTOR
            and not datos["carrera"]
            and Area.objects.filter(activa=True).count() != 1
        ):
            raise ValidationError(
                {
                    "carrera": "Selecciona una carrera para determinar el área del director"
                }
            )
        usuario = aprobar_cuenta(solicitud.usuario, datos, revisor=request.user)
        UsuarioAutorizado.objects.update_or_create(
            email=usuario.email,
            defaults={
                campo: getattr(usuario, campo)
                for campo in [
                    "rut",
                    "nombre_completo",
                    "rol",
                    "carrera",
                    "area",
                    "sede",
                ]
            }
            | {"activo": True},
        )
        solicitud.refresh_from_db()
        return Response(self.get_serializer(solicitud).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def rechazar(self, request, pk=None):
        solicitud = self.get_object()
        if (
            solicitud.estado != "PENDIENTE"
            or solicitud.usuario.estado_cuenta != EstadoCuenta.PENDIENTE_APROBACION
        ):
            raise ValidationError("La solicitud no está pendiente")
        motivo = request.data.get("motivo", "")
        if not isinstance(motivo, str) or not motivo.strip() or len(motivo) > 300:
            raise ValidationError(
                {"motivo": "Indica un motivo de hasta 300 caracteres"}
            )
        solicitud.estado = "RECHAZADA"
        solicitud.motivo_rechazo = motivo.strip()
        solicitud.revisada_por = request.user
        solicitud.revisada_en = timezone.now()
        solicitud.save()
        solicitud.usuario.cambiar_estado(EstadoCuenta.RECHAZADA)
        return Response(self.get_serializer(solicitud).data)
