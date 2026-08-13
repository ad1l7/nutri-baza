# Разовый пересчёт цен продажи под целевую наценку 67%.
# По решению пользователя пересчитываются ВСЕ блюда с себестоимостью, включая
# те, где цена уже была вбита руками. Блюда без себестоимости пропускаются.
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations

TARGET_PCT = 67


def apply_auto_prices(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    factor = Decimal(1) + Decimal(TARGET_PCT) / Decimal(100)
    for product in Product.objects.exclude(cost=None):
        if not product.cost:      # нулевой себес — тех же данных нет
            continue
        auto = (product.cost * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if product.sale_price != auto or product.sale_price_manual:
            product.sale_price = auto
            product.sale_price_manual = False
            product.save(update_fields=["sale_price", "sale_price_manual"])


def noop(apps, schema_editor):
    """Откат не восстанавливает прежние цены — старых значений мы не храним."""


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0038_product_sale_price_manual"),
    ]

    operations = [
        migrations.RunPython(apply_auto_prices, noop),
    ]
