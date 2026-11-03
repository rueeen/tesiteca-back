from rest_framework import serializers, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Sede, Area, Carrera
from tesis.models import Tesis
from tesis.permisos import visibles


from .serializers import SedeMiniSerializer, CarreraMiniSerializer, MiniSerializer
from .opciones import Region, NivelFormacion
from rest_framework import viewsets
from rest_framework.permissions import BasePermission, AllowAny


class CarreraSerializer(CarreraMiniSerializer):
    class Meta(CarreraMiniSerializer.Meta):
        fields = CarreraMiniSerializer.Meta.fields + ["extensiones_material"]


class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "nombre"]


class SedeAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sede
        fields = ["id", "nombre", "ciudad", "region", "orden", "activa"]


class EsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol == "ADMIN"


class SedesAdmin(viewsets.ModelViewSet):
    permission_classes = [EsAdmin]
    serializer_class = SedeAdminSerializer
    queryset = Sede.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]


class Regiones(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response([{"id": c, "nombre": n} for c, n in Region.choices])


class Niveles(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response([{"id": c, "nombre": n} for c, n in NivelFormacion.choices])


class Sedes(generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    queryset = Sede.objects.filter(activa=True).order_by("orden", "nombre")
    serializer_class = SedeMiniSerializer
    pagination_class = None


class Areas(generics.ListAPIView):
    queryset = Area.objects.filter(activa=True).order_by("nombre")
    serializer_class = AreaSerializer
    pagination_class = None


class Carreras(generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    queryset = Carrera.objects.filter(activa=True, area__activa=True).order_by("nombre")
    serializer_class = CarreraSerializer
    pagination_class = None


class Anios(APIView):
    def get(self, request):
        return Response(
            list(
                visibles(Tesis.objects.all(), request.user)
                .order_by("-anio")
                .values_list("anio", flat=True)
                .distinct()
            )
        )


class Profesores(APIView):
    def get(self, request):
        return Response(
            list(
                visibles(Tesis.objects.all(), request.user)
                .exclude(profesor_guia="")
                .order_by("profesor_guia")
                .values_list("profesor_guia", flat=True)
                .distinct()
            )
        )


class CatalogoTipos(APIView):
    def get(self, request):
        from .serializers import tipo_mini

        return Response(
            [tipo_mini(codigo) for codigo, _ in Tesis._meta.get_field("tipo").choices]
        )
