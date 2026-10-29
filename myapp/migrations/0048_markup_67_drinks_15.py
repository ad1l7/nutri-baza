# Возврат наценки фудзавода: 67% на блюда (включая смузи) и 15% на напитки —
# категория «Доп. товары» (Боржоми, EXPONENTA). Округление вверх до целого
# тенге, как в Product.auto_sale_price. Ручных цен после 0047 нет, все цены
# автоматические; дальше их держит Product.save().

from decimal import Decimal, ROUND_CEILING

from django.db import migrations

DISH_PCT = 67
DRINK_PCT = 15
DRINKS_CATEGORY_KEY = "extra"


def forwards(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    drinks = set(
        Product.objects.filter(meal_categories__key=DRINKS_CATEGORY_KEY)
        .values_list("pk", flat=True)
    )
    for p in Product.objects.all():
        pct = DRINK_PCT if p.pk in drinks else DISH_PCT
        factor = Decimal(1) + Decimal(pct) / Decimal(100)
        p.sale_price_manual = False
        if p.cost:
            p.sale_price = (Decimal(str(p.cost)) * factor).quantize(
                Decimal("1"), rounding=ROUND_CEILING)
        p.save(update_fields=["sale_price", "sale_price_manual"])


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0047_markup_3pct"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
