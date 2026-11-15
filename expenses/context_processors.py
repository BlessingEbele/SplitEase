from django.conf import settings


def currency(request):
    return {"currency": getattr(settings, "SPLITEASE_CURRENCY", "$")}
