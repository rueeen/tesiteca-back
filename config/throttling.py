from rest_framework.throttling import ScopedRateThrottle


class ThrottleIP(ScopedRateThrottle):
    def get_ident(self, request):
        # Solo el middleware de firma establece ip_real. No confiar en X-Forwarded-For.
        return getattr(request, "ip_real", None) or request.META.get("REMOTE_ADDR", "")
