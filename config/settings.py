from pathlib import Path
from datetime import timedelta
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "channels",
    "notificaciones",
    "corsheaders",
    "django_filters",
    "academico",
    "usuarios",
    "tesis",
    "privacidad",
]
MIDDLEWARE = [
    "config.middleware.ProxyNetlifyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}
AUTH_USER_MODEL = "usuarios.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ["email", "nombre_completo"]},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "es-cl"
TIME_ZONE = config("TIME_ZONE", default="America/Santiago")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
PRIVATE_MEDIA_ROOT = Path(
    config("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media"))
).resolve()
MAX_PDF_MB = config("MAX_PDF_MB", default=30, cast=int)
MAX_MATERIAL_MB = config("MAX_MATERIAL_MB", default=50, cast=int)
DATA_UPLOAD_MAX_MEMORY_SIZE = (MAX_PDF_MB + MAX_MATERIAL_MB + 2) * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
ALLOWED_EMAIL_DOMAINS = config(
    "ALLOWED_EMAIL_DOMAINS", default="inacapmail.cl,inacap.cl", cast=Csv()
)
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS", default="http://localhost:5173", cast=Csv()
)
CORS_EXPOSE_HEADERS = ["Content-Disposition"]
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="Biblioteca de Tesis <no-reply@example.com>"
)
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "config.paginacion.Paginacion",
    "PAGE_SIZE": 12,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "registro": "5/hour",
        "login": "20/min",
        "cuentas": "20/min",
        "refresh": "30/min",
        "ticket": "20/min",
        "salud": "30/min",
    },
}
if not DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer"
    ]

SIMPLE_JWT = {
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("ACCESS_TOKEN_MINUTES", default=10, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("REFRESH_TOKEN_DAYS", default=7, cast=int)
    ),
}

FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700

FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173").rstrip("/")
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS", default="http://localhost:5173", cast=Csv()
)
WS_ALLOWED_ORIGINS = config(
    "WS_ALLOWED_ORIGINS", default="http://localhost:5173", cast=Csv()
)
SECURE_COOKIES = config("SECURE_COOKIES", default=False, cast=bool)
REFRESH_COOKIE_NAME = config("REFRESH_COOKIE_NAME", default="tesiteca_refresh")
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=10, cast=int)
NOTIFICACIONES_WS = config("NOTIFICACIONES_WS", default=False, cast=bool)
NETLIFY_PROXY_SECRET = config("NETLIFY_PROXY_SECRET", default="")
NETLIFY_SITE_URL = config("NETLIFY_SITE_URL", default="")
EXIGIR_PROXY_NETLIFY = config("EXIGIR_PROXY_NETLIFY", default=False, cast=bool)
APP_VERSION = config("APP_VERSION", default="dev")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
    SESSION_COOKIE_SECURE = SECURE_COOKIES
    CSRF_COOKIE_SECURE = SECURE_COOKIES

from corsheaders.defaults import default_headers

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = list(dict.fromkeys([*default_headers, "x-requested-with"]))
REDIS_URL = config("REDIS_URL", default="")
# InMemory solo comunica HTTP y WS dentro del mismo proceso ASGI, no entre WSGI y ASGI.
CHANNEL_LAYERS = (
    {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
    if REDIS_URL
    else {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
ASGI_APPLICATION = "config.asgi.application"

PASSWORD_RESET_TIMEOUT = 3600
NOTIFICAR_APROBACION_POR_CORREO = False
VISIBILIDAD_ENTRE_SEDES = config("VISIBILIDAD_ENTRE_SEDES", default=True, cast=bool)

PREAPROBACION_LISTA_BLANCA = config(
    "PREAPROBACION_LISTA_BLANCA", default=True, cast=bool
)

# Versiones de textos aprobados por INACAP y plazos de minimización.
POLITICA_PRIVACIDAD_VERSION = config("POLITICA_PRIVACIDAD_VERSION", default="2026-11")
AUTORIZACION_PUBLICACION_VERSION = config(
    "AUTORIZACION_PUBLICACION_VERSION", default="2026-11"
)
RETENCION_LECTURAS_DIAS = config("RETENCION_LECTURAS_DIAS", default=365, cast=int)
RETENCION_SOLICITUDES_RECHAZADAS_DIAS = config(
    "RETENCION_SOLICITUDES_RECHAZADAS_DIAS", default=180, cast=int
)
RETENCION_CUENTAS_INACTIVAS_DIAS = config(
    "RETENCION_CUENTAS_INACTIVAS_DIAS", default=0, cast=int
)
CONTACTO_PRIVACIDAD = config("CONTACTO_PRIVACIDAD", default="")
