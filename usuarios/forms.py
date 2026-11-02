from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import Usuario


class CrearUsuarioForm(UserCreationForm):
    class Meta:
        model = Usuario
        fields = ["email", "nombre_completo", "rol"]


class EditarUsuarioForm(UserChangeForm):
    class Meta:
        model = Usuario
        fields = "__all__"
