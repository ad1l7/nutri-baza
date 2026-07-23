# Категория «Доп. товары»: создаём запись категории на сайте и сопоставление
# с подгруппой iiko «ПП* Доп. товары». Название сопоставления регистр не важен —
# при синхронизации оно нормализуется (см. iiko_sync._normalize_label).

from django.db import migrations

IIKO_NAME = "ПП* Доп. товары"
SLOT_KEY = "extra"


def forwards(apps, schema_editor):
    MealCategory = apps.get_model("myapp", "MealCategory")
    IikoCategoryMap = apps.get_model("myapp", "IikoCategoryMap")
    MealCategory.objects.get_or_create(key=SLOT_KEY)
    IikoCategoryMap.objects.update_or_create(
        iiko_name=IIKO_NAME, defaults={"slot_key": SLOT_KEY}
    )


def backwards(apps, schema_editor):
    MealCategory = apps.get_model("myapp", "MealCategory")
    IikoCategoryMap = apps.get_model("myapp", "IikoCategoryMap")
    IikoCategoryMap.objects.filter(iiko_name=IIKO_NAME).delete()
    MealCategory.objects.filter(key=SLOT_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0028_alter_clauderationslot_slot_type_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
