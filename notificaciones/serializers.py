from rest_framework import serializers
from .models import Notificacion


class NotificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notificacion
        fields = [
            "id",
            "tipo",
            "titulo",
            "mensaje",
            "enlace",
            "datos",
            "leida",
            "creada",
        ]
        read_only_fields = fields
