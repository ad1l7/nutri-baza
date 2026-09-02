import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

DIABET_PREFIX = "ДИАБЕТ"


def open_diabet_groups(apps, schema_editor):
    """Группы ДИАБЕТ ведёт ограниченный редактор, хотя создавал их не он."""
    ClaudeRationGroup = apps.get_model("myapp", "ClaudeRationGroup")
    ClaudeRationGroup.objects.filter(
        name__istartswith=DIABET_PREFIX
    ).update(shared_editing=True)


def close_diabet_groups(apps, schema_editor):
    ClaudeRationGroup = apps.get_model("myapp", "ClaudeRationGroup")
    ClaudeRationGroup.objects.update(shared_editing=False)


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0043_round_up_sale_price'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='userrights',
            name='can_edit_claude_rations',
            field=models.BooleanField(
                default=False,
                help_text='Читатель сможет создавать группы и рационы во вкладке '
                          '«Рационы Claude» и править СВОИ, а также группы, отмеченные '
                          'галочкой «Открыта ограниченным редакторам». Чужие рационы '
                          'останутся только для чтения, остальные вкладки — тоже.',
                verbose_name='Может вести рационы Claude',
            ),
        ),
        migrations.AddField(
            model_name='clauderationgroup',
            name='created_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='claude_groups',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Создал',
            ),
        ),
        migrations.AddField(
            model_name='clauderationgroup',
            name='shared_editing',
            field=models.BooleanField(
                default=False,
                help_text='Группу смогут править все, у кого есть право '
                          '«Может вести рационы Claude», даже если создали её не они.',
                verbose_name='Открыта ограниченным редакторам',
            ),
        ),
        migrations.AddField(
            model_name='clauderation',
            name='created_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='claude_rations',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Создал',
            ),
        ),
        migrations.RunPython(open_diabet_groups, close_diabet_groups),
    ]
