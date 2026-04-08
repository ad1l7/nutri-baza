from django import template
from decimal import Decimal

register = template.Library()


@register.filter
def smart_num(value):
    if value is None or value == '':
        return '—'
    try:
        d = Decimal(str(value))
        formatted = '{:f}'.format(d)
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted
    except Exception:
        return value


@register.filter
def get_item(dictionary, key):
    """Получить значение из словаря по ключу в шаблоне."""
    return dictionary.get(key, '')


@register.filter
def div(value, arg):
    """Деление для прогресс-бара."""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0


@register.filter
def mul(value, arg):
    """Умножение."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0