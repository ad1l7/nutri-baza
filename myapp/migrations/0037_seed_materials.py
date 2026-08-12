# Начальный список материалов — тот, что раньше был зашит в коде экспорта
# (ORDER_SHEET_MATERIALS) и печатался в конце каждого заявочного листа.
from django.db import migrations

MATERIALS = [
    ("27602", "У* Термопакет серый 28*28*20",              "1 шт"),
    ("27605", "У* Термопакет оранжевый 30*30*20",          "1 шт"),
    ("27603", "У* Термопакет зеленый 28*28*20",            "1 шт"),
    ("27604", "У* Термопакет красный 30*30*20",            "1 шт"),
    ("99727", "У* Набор одноразовый (вилка,ложка,салфетка)", "1 шт"),
    ("31880", "С* Вода Тассай без газа 777 мл",            "1 шт"),
    ("",      "Хладогент",                                  "1 шт"),
]


def seed(apps, schema_editor):
    Material = apps.get_model("myapp", "Material")
    if Material.objects.exists():
        return
    for index, (article, name, unit) in enumerate(MATERIALS):
        Material.objects.create(article=article, name=name, unit=unit, order=index)


def unseed(apps, schema_editor):
    Material = apps.get_model("myapp", "Material")
    Material.objects.filter(name__in=[m[1] for m in MATERIALS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0036_material"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
