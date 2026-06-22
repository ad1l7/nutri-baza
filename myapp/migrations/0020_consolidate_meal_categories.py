# Объединение 12 категорий блюд в 8.
# Переносит связи блюдо↔категория и slot_type рационов на новые ключи,
# затем удаляет устаревшие категории. Рационы и блюда сохраняются.

from django.db import migrations

# Старый ключ → новый ключ
OLD_TO_NEW = {
    'breakfast_250': 'breakfast',
    'breakfast_400': 'breakfast',
    'second_400':    'hot_400',
    'second_500':    'hot_500',
    'soup_200':      'soup',
    'soup_300':      'soup',
    'salad_150':     'salad',
    'salad_250':     'salad',
    'dessert_100':   'dessert',
    'dessert_300':   'dessert',
    # smoothie, sandwich — ключи не меняются (меняется только их название в SLOT_TYPES)
}

NEW_KEYS = ['breakfast', 'hot_400', 'hot_500', 'soup', 'salad', 'dessert', 'smoothie', 'sandwich']


def forwards(apps, schema_editor):
    MealCategory = apps.get_model('myapp', 'MealCategory')
    Product = apps.get_model('myapp', 'Product')
    RationSlot = apps.get_model('myapp', 'RationSlot')

    # 1. Гарантируем наличие всех новых категорий
    new_cat = {}
    for key in NEW_KEYS:
        obj, _ = MealCategory.objects.get_or_create(key=key)
        new_cat[key] = obj

    # 2. Переносим связи блюдо↔категория (объединение старых в новые)
    for product in Product.objects.prefetch_related('meal_categories').all():
        current_keys = list(product.meal_categories.values_list('key', flat=True))
        if not current_keys:
            continue
        target_keys = set()
        for ck in current_keys:
            target_keys.add(OLD_TO_NEW.get(ck, ck))  # старые → новые, остальные (smoothie/sandwich/уже новые) как есть
        target_objs = [new_cat[k] for k in target_keys if k in new_cat]
        product.meal_categories.set(target_objs)

    # 3. Переносим slot_type в собранных рационах
    for old_key, new_key in OLD_TO_NEW.items():
        RationSlot.objects.filter(slot_type=old_key).update(slot_type=new_key)

    # 4. Удаляем устаревшие категории
    MealCategory.objects.filter(key__in=OLD_TO_NEW.keys()).delete()


def backwards(apps, schema_editor):
    # Обратный перенос невозможен без потерь (объединение 2→1 необратимо).
    # Восстановление — только из бэкапа БД.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0019_alter_mealcategory_key_alter_rationslot_slot_type'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
