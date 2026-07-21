"""
Копирует рационы из обычной вкладки (Ration) во вкладку Claude (ClaudeRation).

Копирование, а не перенос: исходные рационы остаются на месте, данные двух
вкладок после копирования полностью независимы (отдельные таблицы).

По умолчанию рацион пропускается, если в Claude уже есть рацион с таким же
названием в группе с таким же названием — чтобы повторный запуск не плодил
дубликаты. Флаг --force отключает эту проверку.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from myapp.models import (
    ClaudeRation,
    ClaudeRationGroup,
    ClaudeRationSlot,
    Ration,
    RationGroup,
)


class Command(BaseCommand):
    help = "Копирует все рационы из вкладки «Рационы» во вкладку «Рационы Claude»"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Копировать даже те рационы, что уже есть в Claude (по названию)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Показать, что будет скопировано, ничего не записывая",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]

        # Существующие пары (группа, рацион) в Claude — для пропуска дублей.
        existing = {
            (r.group.name if r.group_id else None, r.name)
            for r in ClaudeRation.objects.select_related("group")
        }

        # Группы: одноимённую переиспользуем, иначе создаём.
        group_map = {}
        groups_created = 0
        for group in RationGroup.objects.all():
            target = ClaudeRationGroup.objects.filter(name=group.name).first()
            if target is None:
                if not dry_run:
                    target = ClaudeRationGroup.objects.create(
                        name=group.name, description=group.description,
                    )
                groups_created += 1
                self.stdout.write(f"  + группа: {group.name}")
            group_map[group.id] = target

        rations_copied = 0
        slots_copied = 0
        skipped = 0

        for ration in Ration.objects.select_related("group").prefetch_related("slots"):
            group_name = ration.group.name if ration.group_id else None
            if not force and (group_name, ration.name) in existing:
                skipped += 1
                self.stdout.write(f"  = пропуск (уже есть): {ration.name}")
                continue

            self.stdout.write(f"  + рацион: {ration.name}")
            rations_copied += 1

            if dry_run:
                slots_copied += ration.slots.count()
                continue

            new_ration = ClaudeRation.objects.create(
                group=group_map.get(ration.group_id),
                name=ration.name,
                kcal_category=ration.kcal_category,
                notes=ration.notes,
                order=ration.order,
            )
            ClaudeRationSlot.objects.bulk_create([
                ClaudeRationSlot(
                    ration=new_ration,
                    meal_time_id=slot.meal_time_id,
                    slot_type=slot.slot_type,
                    product_id=slot.product_id,
                    order=slot.order,
                )
                for slot in ration.slots.all()
            ])
            slots_copied += ration.slots.count()

        self.stdout.write(self.style.SUCCESS(
            f"\nГрупп создано: {groups_created} | "
            f"рационов скопировано: {rations_copied} | "
            f"слотов скопировано: {slots_copied} | "
            f"пропущено: {skipped}"
        ))

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: изменения не сохранены"))
            transaction.set_rollback(True)
