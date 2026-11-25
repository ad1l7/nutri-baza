# Категория «Материалы» (25.11.2026): упаковка, вода и т.п. со вкладки
# «Материалы». Позиции заводит синхронизация с O·ERP по артикулам этой вкладки
# (oerp_sync.collect_from_oerp), здесь — только запись категории.

from django.db import migrations

SLOT_KEY = "materials"


def forwards(apps, schema_editor):
    MealCategory = apps.get_model("myapp", "MealCategory")
    MealCategory.objects.get_or_create(key=SLOT_KEY)


def backwards(apps, schema_editor):
    MealCategory = apps.get_model("myapp", "MealCategory")
    MealCategory.objects.filter(key=SLOT_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0053_materials_custom_markup"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
