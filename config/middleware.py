import ipaddress
import jwt
from django.conf import settings
from django.http import JsonResponse
from django.utils.cache import patch_vary_headers


class ProxyNetlifyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.via_proxy = False
        request.ip_real = None
        firma = request.headers.get("x-nf-sign")
        if settings.NETLIFY_PROXY_SECRET and settings.NETLIFY_SITE_URL and firma:
            try:
                payload = jwt.decode(
                    firma,
                    settings.NETLIFY_PROXY_SECRET,
                    algorithms=["HS256"],
                    issuer="netlify",
                    options={"require": ["exp", "iss"]},
                    leeway=30,
                )
                request.via_proxy = (
                    payload.get("site_url") == settings.NETLIFY_SITE_URL
                    and payload.get("deploy_context") == "production"
                )
            except (jwt.InvalidTokenError, TypeError, ValueError):
                # No registrar firma, payload ni secreto.
                pass
        if request.via_proxy:
            try:
                request.ip_real = str(
                    ipaddress.ip_address(
                        request.headers.get("x-nf-client-connection-ip", "")
                    )
                )
            except ValueError:
                pass
        es_api = request.path.startswith("/api/")
        if (
            es_api
            and request.path != "/api/salud/"
            and settings.EXIGIR_PROXY_NETLIFY
            and not request.via_proxy
        ):
            response = JsonResponse(
                {"detail": "Acceso solo a través del sitio oficial"}, status=403
            )
        else:
            response = self.get_response(request)
        if es_api:
            if not response.has_header("Cache-Control"):
                response["Cache-Control"] = "no-store, private"
            patch_vary_headers(response, ["Authorization", "Cookie"])
        return response
