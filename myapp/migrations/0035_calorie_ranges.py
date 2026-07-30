"""Калораж хранит границы КБЖУ как произвольный диапазон «от … до …».

Раньше было «цель ± погрешность» — симметрично и только вокруг цели.
Теперь границы задаются вручную, а старые данные переносятся так:
    от = цель - погрешность,  до = цель + погрешность
Цель по ккал (kcal) остаётся — по ней рационы находят свой калораж.
Цели по БЖУ больше нет, они полностью описываются диапазоном.
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    CalorieCategory = apps.get_model("myapp", "CalorieCategory")
    for c in CalorieCategory.objects.all():
        CalorieCategory.objects.filter(pk=c.pk).update(
            kcal_min=max(0, c.kcal - c.kcal_tolerance),
            kcal_max=c.kcal + c.kcal_tolerance,
            protein_min=max(0, c.protein - c.protein_tolerance),
            protein_max=c.protein + c.protein_tolerance,
            fat_min=max(0, c.fat - c.fat_tolerance),
            fat_max=c.fat + c.fat_tolerance,
            carbs_min=max(0, c.carbs - c.carbs_tolerance),
            carbs_max=c.carbs + c.carbs_tolerance,
        )


def backwards(apps, schema_editor):
    CalorieCategory = apps.get_model("myapp", "CalorieCategory")
    for c in CalorieCategory.objects.all():
        CalorieCategory.objects.filter(pk=c.pk).update(
            kcal_tolerance=max(c.kcal_max - c.kcal, c.kcal - c.kcal_min, 0),
            protein=(c.protein_min + c.protein_max) // 2,
            protein_tolerance=(c.protein_max - c.protein_min) // 2,
            fat=(c.fat_min + c.fat_max) // 2,
            fat_tolerance=(c.fat_max - c.fat_min) // 2,
            carbs=(c.carbs_min + c.carbs_max) // 2,
            carbs_tolerance=(c.carbs_max - c.carbs_min) // 2,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0034_drop_ration_template_and_norm"),
    ]

    operations = [
        migrations.AddField(
            model_name="caloriecategory",
            name="kcal_min",
            field=models.PositiveIntegerField(default=0, verbose_name="Ккал — от"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="kcal_max",
            field=models.PositiveIntegerField(default=0, verbose_name="Ккал — до"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="protein_min",
            field=models.PositiveIntegerField(default=0, verbose_name="Белки — от, г"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="protein_max",
            field=models.PositiveIntegerField(default=0, verbose_name="Белки — до, г"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="fat_min",
            field=models.PositiveIntegerField(default=0, verbose_name="Жиры — от, г"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="fat_max",
            field=models.PositiveIntegerField(default=0, verbose_name="Жиры — до, г"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="carbs_min",
            field=models.PositiveIntegerField(default=0, verbose_name="Углеводы — от, г"),
        ),
        migrations.AddField(
            model_name="caloriecategory",
            name="carbs_max",
            field=models.PositiveIntegerField(default=0, verbose_name="Углеводы — до, г"),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="caloriecategory", name="kcal_tolerance"),
        migrations.RemoveField(model_name="caloriecategory", name="protein"),
        migrations.RemoveField(model_name="caloriecategory", name="protein_tolerance"),
        migrations.RemoveField(model_name="caloriecategory", name="fat"),
        migrations.RemoveField(model_name="caloriecategory", name="fat_tolerance"),
        migrations.RemoveField(model_name="caloriecategory", name="carbs"),
        migrations.RemoveField(model_name="caloriecategory", name="carbs_tolerance"),
    ]
