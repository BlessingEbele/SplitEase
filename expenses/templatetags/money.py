from decimal import Decimal

from django import template
from django.conf import settings

from ..forms import display_name as _display_name

register = template.Library()


def format_money(value, signed=False):
    """Format a Decimal as e.g. ``$1,234.50`` (or ``+$1,234.50`` when signed)."""
    if value is None:
        return "—"
    value = Decimal(value)
    symbol = getattr(settings, "SPLITEASE_CURRENCY", "$")
    text = f"{symbol}{abs(value):,.2f}"
    if value < 0:
        return f"−{text}"
    if signed and value > 0:
        return f"+{text}"
    return text


@register.filter
def money(value):
    return format_money(value)


@register.filter
def signed_money(value):
    return format_money(value, signed=True)


@register.filter
def absolute(value):
    return abs(value) if value is not None else value


@register.filter
def tone(value):
    """CSS tone class for a balance: owed (positive), owe (negative) or muted."""
    if value is None or value == 0:
        return "muted"
    return "owed" if value > 0 else "owe"


@register.filter
def display_name(user):
    return _display_name(user)


@register.filter
def initials(user):
    name = _display_name(user)
    parts = [p for p in name.replace("@", " ").replace(".", " ").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"
