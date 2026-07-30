"""Переносит калоражи из старых RationNorm + RationTemplate в CalorieCategory.

Раньше нормы КБЖУ (RationNorm) и набор приёмов пищи (RationTemplate) жили
в двух разных моделях и правились только в админке. Теперь это один калораж,
который редактируется во вкладке «Калоражи».

Нормы хранились как мин–макс, а калораж хранит цель ± погрешность:
    цель = (мин + макс) / 2,  погрешность = (макс - мин) / 2
"""
from django.db import migrations


DEFAULT_NAMES = {1200: "1200 ккал", 1500: "1500 ккал", 1800: "1800 ккал", 2500: "2500 ккал"}


def _target_and_tolerance(lo, hi):
    lo, hi = int(lo or 0), int(hi or 0)
    if hi < lo:
        lo, hi = hi, lo
    return (lo + hi) // 2, (hi - lo) // 2


def forwards(apps, schema_editor):
    CalorieCategory = apps.get_model("myapp", "CalorieCategory")
    CalorieCategoryMeal = apps.get_model("myapp", "CalorieCategoryMeal")
    RationNorm = apps.get_model("myapp", "RationNorm")
    RationTemplate = apps.get_model("myapp", "RationTemplate")
    Ration = apps.get_model("myapp", "Ration")
    ClaudeRation = apps.get_model("myapp", "ClaudeRation")

    # Все калорийности, которые где-либо используются, — чтобы ни один
    # существующий рацион не остался без своего калоража.
    kcals = set(RationNorm.objects.values_list("kcal_category", flat=True))
    kcals |= set(RationTemplate.objects.values_list("kcal_category", flat=True))
    kcals |= set(Ration.objects.values_list("kcal_category", flat=True))
    kcals |= set(ClaudeRation.objects.values_list("kcal_category", flat=True))
    kcals = {k for k in kcals if k}

    for order, kcal in enumerate(sorted(kcals)):
        if CalorieCategory.objects.filter(kcal=kcal).exists():
            continue

        fields = {
            "name": DEFAULT_NAMES.get(kcal, f"{kcal} ккал"),
            "kcal": kcal,
            "order": order,
            # Дефолты на случай, если нормы для этой калорийности не было
            "kcal_tolerance": 50,
            "protein": 0, "protein_tolerance": 5,
            "fat": 0, "fat_tolerance": 5,
            "carbs": 0, "carbs_tolerance": 10,
        }

        norm = RationNorm.objects.filter(kcal_category=kcal).first()
        if norm:
            _, fields["kcal_tolerance"] = _target_and_tolerance(norm.kcal_min, norm.kcal_max)
            fields["protein"], fields["protein_tolerance"] = _target_and_tolerance(norm.protein_min, norm.protein_max)
            fields["fat"], fields["fat_tolerance"] = _target_and_tolerance(norm.fat_min, norm.fat_max)
            fields["carbs"], fields["carbs_tolerance"] = _target_and_tolerance(norm.carbs_min, norm.carbs_max)

        category = CalorieCategory.objects.create(**fields)

        tmpl = RationTemplate.objects.filter(kcal_category=kcal).first()
        if not tmpl:
            continue
        seen = set()
        for i, slot in enumerate(tmpl.slots.order_by("order", "id")):
            if not slot.meal_time_id or slot.meal_time_id in seen:
                continue
            seen.add(slot.meal_time_id)
            CalorieCategoryMeal.objects.create(
                category=category, meal_time_id=slot.meal_time_id, order=i,
            )


def backwards(apps, schema_editor):
    """Возврат: восстанавливаем нормы и шаблоны из калоражей."""
    CalorieCategory = apps.get_model("myapp", "CalorieCategory")
    RationNorm = apps.get_model("myapp", "RationNorm")
    RationTemplate = apps.get_model("myapp", "RationTemplate")
    RationTemplateSlot = apps.get_model("myapp", "RationTemplateSlot")

    for category in CalorieCategory.objects.all():
        RationNorm.objects.update_or_create(
            kcal_category=category.kcal,
            defaults={
                "kcal_min": max(0, category.kcal - category.kcal_tolerance),
                "kcal_max": category.kcal + category.kcal_tolerance,
                "protein_min": max(0, category.protein - category.protein_tolerance),
                "protein_max": category.protein + category.protein_tolerance,
                "fat_min": max(0, category.fat - category.fat_tolerance),
                "fat_max": category.fat + category.fat_tolerance,
                "carbs_min": max(0, category.carbs - category.carbs_tolerance),
                "carbs_max": category.carbs + category.carbs_tolerance,
            },
        )
        tmpl, _ = RationTemplate.objects.get_or_create(kcal_category=category.kcal)
        tmpl.slots.all().delete()
        for meal in category.meals.order_by("order", "id"):
            RationTemplateSlot.objects.create(
                template=tmpl, meal_time_id=meal.meal_time_id, order=meal.order,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0032_calorie_category"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
