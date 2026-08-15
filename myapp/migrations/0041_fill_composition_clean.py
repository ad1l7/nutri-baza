# Разовое заполнение чистого состава по справочнику ингредиентов.
# Дальше поле пересчитывается само в Product.save() (в том числе на синхронизации).
from django.db import migrations

from myapp.ingredient_aliases import clean_composition


def fill(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    for product in Product.objects.exclude(composition=None).exclude(composition=""):
        clean = clean_composition(product.composition)
        if clean != product.composition_clean:
            product.composition_clean = clean
            product.save(update_fields=["composition_clean"])


def unfill(apps, schema_editor):
    Product = apps.get_model("myapp", "Product")
    Product.objects.update(composition_clean="")


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0040_product_composition_clean_alter_product_composition"),
    ]

    operations = [
        migrations.RunPython(fill, unfill),
    ]
