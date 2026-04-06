from django import template
from decimal import Decimal

register = template.Library()


@register.filter
def smart_num(value):
    if value is None or value == '':
        return '—'
    try:
        d = Decimal(str(value))
        # Убираем хвостовые нули вручную через форматирование
        formatted = '{:f}'.format(d)          # никогда не даст E+2
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted
    except Exception:
        return value