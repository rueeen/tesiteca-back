from django.conf import settings

RUTA_COOKIE = "/api/auth/"


def poner_refresh(response, token):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        str(token),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="Strict",
        path=RUTA_COOKIE,
    )
    return response


def borrar_refresh(response):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        "",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="Strict",
        path=RUTA_COOKIE,
    )
    return response
