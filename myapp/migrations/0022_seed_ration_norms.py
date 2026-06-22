# Засев норм КБЖУ по категориям калорийности (значения из таблицы).
# Калорийный коридор задан ±50 ккал — при необходимости меняется в админке.

from django.db import migrations

NORMS = {
    1200: dict(kcal_min=1150, kcal_max=1250, protein_min=77,  protein_max=83,  fat_min=55, fat_max=60, carbs_min=120, carbs_max=150),
    1500: dict(kcal_min=1450, kcal_max=1550, protein_min=82,  protein_max=88,  fat_min=60, fat_max=70, carbs_min=130, carbs_max=180),
    1800: dict(kcal_min=1750, kcal_max=1850, protein_min=92,  protein_max=98,  fat_min=75, fat_max=80, carbs_min=150, carbs_max=200),
    2500: dict(kcal_min=2450, kcal_max=2550, protein_min=97,  protein_max=103, fat_min=80, fat_max=90, carbs_min=190, carbs_max=250),
}


def forwards(apps, schema_editor):
    RationNorm = apps.get_model('myapp', 'RationNorm')
    for kcal, vals in NORMS.items():
        RationNorm.objects.update_or_create(kcal_category=kcal, defaults=vals)


def backwards(apps, schema_editor):
    RationNorm = apps.get_model('myapp', 'RationNorm')
    RationNorm.objects.filter(kcal_category__in=NORMS.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0021_rationnorm'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
