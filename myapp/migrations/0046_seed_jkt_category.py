# Категория «ЖКТ»: запись категории на сайте, сопоставление с группой внешнего
# меню iiko «ЖКТ (желудочно кишечный тракт)» и привязка блюд, которые уже
# лежат в этой группе. Дальше синхронизация ставит категорию сама — по записи
# сопоставления (см. iiko_sync._build_label_to_key).

from django.db import migrations

IIKO_NAME = "ЖКТ (желудочно кишечный тракт)"
SLOT_KEY = "jkt"


def forwards(apps, schema_editor):
    MealCategory = apps.get_model("myapp", "MealCategory")
    IikoCategoryMap = apps.get_model("myapp", "IikoCategoryMap")
    Product = apps.get_model("myapp", "Product")

    category, _ = MealCategory.objects.get_or_create(key=SLOT_KEY)
    IikoCategoryMap.objects.update_or_create(
        iiko_name=IIKO_NAME, defaults={"slot_key": SLOT_KEY}
    )
    # Синхронизация ставит ровно одну категорию сайта (meal_categories.set),
    # здесь делаем так же, чтобы до следующего синка блюдо не висело в двух.
    for product in Product.objects.filter(iiko_category__iexact=IIKO_NAME):
        product.meal_categories.set([category])


def backwards(apps, schema_editor):
    MealCategory = apps.get_model("myapp", "MealCategory")
    IikoCategoryMap = apps.get_model("myapp", "IikoCategoryMap")
    IikoCategoryMap.objects.filter(iiko_name=IIKO_NAME).delete()
    MealCategory.objects.filter(key=SLOT_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0045_add_jkt_category"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
