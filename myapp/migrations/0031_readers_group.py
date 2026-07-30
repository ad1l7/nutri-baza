# Группа «readers» — роль только для чтения. Наличие пользователя в этой
# группе делает его читателем (см. myapp/roles.py). Сам пользователь Saule
# заводится отдельно (данные, не код).

from django.db import migrations


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="readers")


def backwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="readers").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0030_product_sale_price"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
