# Актуальные названия категорий из iiko (с префиксом «ПП* », капсом) → категории сайта.
# Дальше редактируется в админке.

from django.db import migrations

MAPPING = {
    'ПП* ЗАВТРАК':               'breakfast',
    'ПП* ГОРЯЧЕЕ 400-500 ккал':  'hot_400',
    'ПП* ГОРЯЧЕЕ 500-600 ккал':  'hot_500',
    'ПП* СУП':                   'soup',
    'ПП* САЛАТ':                 'salad',
    'ПП* ВЫПЕЧКА/ДЕСЕРТ':        'dessert',
    'ПП* СМУЗИ':                 'smoothie',
    'ПП* СЭНДВИЧИ':              'sandwich',
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
        ('myapp', '0024_seed_iiko_category_map'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
