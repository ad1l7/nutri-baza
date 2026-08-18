# Цены продажи теперь округляются вверх до целых тенге (было — до копеек).
# Пересчитываем все автоматические цены; вручную заданные не трогаем.
from decimal import Decimal, ROUND_CEILING

from django.db import migrations

TARGET_PCT = 67


def round_up(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    factor = Decimal(1) + Decimal(TARGET_PCT) / Decimal(100)
    for product in Product.objects.filter(sale_price_manual=False).exclude(cost=None):
        if not product.cost:
            continue
        auto = (product.cost * factor).quantize(Decimal("1"), rounding=ROUND_CEILING)
        if product.sale_price != auto:
            product.sale_price = auto
            product.save(update_fields=["sale_price"])


def noop(apps, schema_editor):
    """Обратно не откатываем: прежние цены с копейками нигде не сохранены."""


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0042_userrights"),
    ]

    operations = [
        migrations.RunPython(round_up, noop),
    ]
