# Засев таблицы сопоставления категорий iiko → категории сайта.
# Старые и новые (актуальные) названия из iiko. Дальше редактируется в админке.

from django.db import migrations

MAPPING = {
    # старые дробные названия
    'Завтрак 250–350 ккал':        'breakfast',
    'Завтрак 400–500 ккал':        'breakfast',
    'Второе 400–500 ккал':         'hot_400',
    'Второе 500–600 ккал':         'hot_500',
    'Суп 200 ккал':                'soup',
    'Суп 300 ккал':                'soup',
    'Салат 150–250 ккал':          'salad',
    'Салат 250–350 ккал':          'salad',
    'Выпечка/Десерт 100–250 ккал': 'dessert',
    'Выпечка/Десерт 300–350 ккал': 'dessert',
    'Смузи 100–150 ккал':          'smoothie',
    'Сэндвич 300–350 ккал':        'sandwich',
    # новые (как на сайте)
    'Завтрак':          'breakfast',
    'Горячее 400-500':  'hot_400',
    'Горячее 500-600':  'hot_500',
    'Суп':              'soup',
    'Салат':            'salad',
    'Выпечка/Десерт':   'dessert',
    'Смузи':            'smoothie',
    'Сэндвичи':         'sandwich',
}


def forwards(apps, schema_editor):
    IikoCategoryMap = apps.get_model('myapp', 'IikoCategoryMap')
    for name, key in MAPPING.items():
        IikoCategoryMap.objects.update_or_create(iiko_name=name, defaults={'slot_key': key})


def backwards(apps, schema_editor):
    IikoCategoryMap = apps.get_model('myapp', 'IikoCategoryMap')
    IikoCategoryMap.objects.filter(iiko_name__in=MAPPING.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0023_iikocategorymap'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
