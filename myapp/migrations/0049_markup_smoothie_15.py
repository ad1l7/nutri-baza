# Смузи переходят к напиткам: наценка 15% вместо 67% (Product.DRINKS_CATEGORY_KEYS).
# Пересчитываем только автоматические цены смузи, вверх до целого тенге.

from decimal import Decimal, ROUND_CEILING

from django.db import migrations

DRINK_PCT = 15


def forwards(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    factor = Decimal(1) + Decimal(DRINK_PCT) / Decimal(100)
    smoothies = Product.objects.filter(
        meal_categories__key="smoothie", sale_price_manual=False,
    ).exclude(cost__isnull=True).exclude(cost=0).distinct()
    for p in smoothies:
        p.sale_price = (Decimal(str(p.cost)) * factor).quantize(
            Decimal("1"), rounding=ROUND_CEILING)
        p.save(update_fields=["sale_price"])


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0048_markup_67_drinks_15"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
