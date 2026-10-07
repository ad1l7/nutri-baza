# Наценка фудзавода снижена с 67% до 3% (Product.MARKUP_TARGET_PCT): все цены
# продажи пересчитываются на 3%, включая введённые вручную — их возвращаем
# в автоматический режим. Дальше цену держит Product.save().

from decimal import Decimal, ROUND_CEILING

from django.db import migrations

MARKUP_PCT = 3


def forwards(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    factor = Decimal(1) + Decimal(MARKUP_PCT) / Decimal(100)
    for p in Product.objects.all():
        p.sale_price_manual = False
        if p.cost:
            p.sale_price = (Decimal(str(p.cost)) * factor).quantize(
                Decimal("1"), rounding=ROUND_CEILING)
        p.save(update_fields=["sale_price", "sale_price_manual"])


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0046_seed_jkt_category"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
