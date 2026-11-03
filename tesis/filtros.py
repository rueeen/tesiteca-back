import django_filters
from .models import Tesis


class FiltroTesis(django_filters.FilterSet):
    nivel_formacion = django_filters.CharFilter(field_name="carrera__nivel_formacion")
    region = django_filters.CharFilter(field_name="sede__region")
    anio_desde = django_filters.NumberFilter(field_name="anio", lookup_expr="gte")
    anio_hasta = django_filters.NumberFilter(field_name="anio", lookup_expr="lte")
    profesor_guia = django_filters.CharFilter(lookup_expr="icontains")
    palabra_clave = django_filters.CharFilter(
        field_name="palabras_clave", lookup_expr="icontains"
    )
    tiene_repositorio = django_filters.BooleanFilter(method="filtrar_repositorio")

    def filtrar_repositorio(self, qs, nombre, valor):
        ids = Tesis.objects.filter(materiales__tipo="REPOSITORIO").values("id")
        return qs.filter(id__in=ids) if valor else qs.exclude(id__in=ids)

    class Meta:
        model = Tesis
        fields = ["carrera", "sede", "tipo", "anio"]
