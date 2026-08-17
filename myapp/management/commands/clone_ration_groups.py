"""Дублирует группы рационов Claude, помеченные «не удалять».

Оригинал остаётся нетронутым — он служит шаблоном. Копия получает то же
название без пометки и полный набор рационов со слотами (приём пищи,
категория, блюдо, порядок).

    python manage.py clone_ration_groups --dry-run    # только показать
    python manage.py clone_ration_groups              # выполнить

Пометку можно задать своей: --marker "(не трогать)".
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from myapp.models import ClaudeRationGroup, ClaudeRation, ClaudeRationSlot

DEFAULT_MARKER = "(не удалять)"


class Command(BaseCommand):
    help = "Дублирует помеченные группы рационов Claude без пометки в названии"

    def add_arguments(self, parser):
        parser.add_argument("--marker", default=DEFAULT_MARKER,
                            help="Пометка в конце названия (по умолчанию «%s»)" % DEFAULT_MARKER)
        parser.add_argument("--dry-run", action="store_true",
                           help="Показать, что будет сделано, ничего не меняя")

    def handle(self, *args, **options):
        marker = options["marker"]
        dry_run = options["dry_run"]

        groups = [g for g in ClaudeRationGroup.objects.all().order_by("pk")
                  if marker.lower() in (g.name or "").lower()]
        if not groups:
            self.stdout.write("Групп с пометкой «%s» не найдено." % marker)
            return

        for group in groups:
            # Убираем пометку и лишние пробелы: «Рационы 1500  (не удалять)» → «Рационы 1500»
            new_name = re.sub(re.escape(marker), "", group.name, flags=re.IGNORECASE)
            new_name = re.sub(r"\s+", " ", new_name).strip()

            rations = list(group.rations.all().order_by("order", "pk"))
            slots_total = ClaudeRationSlot.objects.filter(ration__group=group).count()

            if ClaudeRationGroup.objects.filter(name=new_name).exists():
                self.stdout.write(self.style.WARNING(
                    "  «%s» → «%s» — пропускаю, такая группа уже есть"
                    % (group.name, new_name)))
                continue

            self.stdout.write("  «%s» → «%s»: рационов %d, слотов %d"
                              % (group.name, new_name, len(rations), slots_total))
            if dry_run:
                continue

            with transaction.atomic():
                copy = ClaudeRationGroup.objects.create(
                    name=new_name, description=group.description,
                )
                for ration in rations:
                    ration_copy = ClaudeRation.objects.create(
                        group=copy, name=ration.name,
                        kcal_category=ration.kcal_category,
                        wishes=ration.wishes, notes=ration.notes,
                        order=ration.order,
                    )
                    ClaudeRationSlot.objects.bulk_create([
                        ClaudeRationSlot(
                            ration=ration_copy, meal_time_id=slot.meal_time_id,
                            slot_type=slot.slot_type, product_id=slot.product_id,
                            order=slot.order,
                        )
                        for slot in ration.slots.all().order_by("order", "pk")
                    ])
            self.stdout.write(self.style.SUCCESS("     создана группа id=%d" % copy.pk))

        if dry_run:
            self.stdout.write("\nЭто был предпросмотр — ничего не изменено.")
