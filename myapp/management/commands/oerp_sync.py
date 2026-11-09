"""Загрузка блюд из O·ERP и сверка с базой.

    python manage.py oerp_sync --compare   # скачать и сравнить, ничего не пишет
    python manage.py oerp_sync --apply     # записать в базу (как кнопка при PRODUCT_SOURCE=oerp)

Сверка — шаг перед переключением с iiko (docs/oerp-source.md): по каждому
блюду сравнивает название, артикул, вес, КБЖУ, состав и себестоимость с тем,
что сейчас в базе. Числа — с округлением до 2 знаков.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from myapp.oerp_sync import (
    OerpClient, collect_from_oerp, compare_with_db, sync_products_from_oerp,
)


class Command(BaseCommand):
    help = "Блюда из O·ERP: --compare (сверка с базой) или --apply (запись)"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--compare", action="store_true", help="Сверить с базой, ничего не писать")
        mode.add_argument("--apply", action="store_true", help="Записать в базу")
        parser.add_argument("--date", help="Дата техкарт и себестоимости ГГГГ-ММ-ДД, по умолчанию сегодня")
        parser.add_argument("--examples", type=int, default=5, help="Сколько примеров расхождений по полю")

    def handle(self, *args, **opts):
        if not settings.OERP_API_KEY:
            raise CommandError("Не задан OERP_API_KEY в .env")

        if opts["apply"]:
            result = sync_products_from_oerp(settings.OERP_API_KEY, settings.OERP_API_URL)
            self.stdout.write(str(result))
            return

        client = OerpClient(settings.OERP_API_KEY, settings.OERP_API_URL)
        collected = collect_from_oerp(client, opts["date"])
        report = compare_with_db(collected)
        st = collected["stats"]
        out = self.stdout.write

        out(f"Блюд в O·ERP: {report['feed']}, нашлось в базе: {report['matched']} "
            f"(тот же iiko_id: {report['same_id']})")
        out(f"Состав: из техкарт {st['with_card']}, из описания {st['from_description']}; "
            f"себестоимость есть у {st['with_cost']}")
        for err in collected["errors"]:
            out(self.style.ERROR(f"Ошибка: {err}"))

        n = opts["examples"]
        out(f"\nНовые (в O·ERP есть, в базе нет): {len(report['new'])}")
        for name in report["new"][:n]:
            out(f"  + {name}")
        out(f"В базе, но нет в папках O·ERP (удалены не будут): {len(report['missing'])}")
        for name in report["missing"][:n]:
            out(f"  - {name}")

        out("\nРасхождения по полям:")
        for field, rows in report["diffs"].items():
            mark = self.style.SUCCESS("ok") if not rows else self.style.WARNING(str(len(rows)))
            out(f"  {field}: {mark}")
            for pk, name, old, new in rows[:n]:
                out(f"      #{pk} {name[:45]}: {self._short(old)} → {self._short(new)}")
        if st["no_cost"]:
            out(f"\nБез себестоимости в O·ERP ({len(st['no_cost'])}, старое значение останется): "
                f"{', '.join(st['no_cost'][:n])}")

    @staticmethod
    def _short(val):
        s = "—" if val is None or val == "" else str(val)
        return s if len(s) <= 70 else s[:67] + "…"
