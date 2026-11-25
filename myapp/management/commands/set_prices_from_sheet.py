"""Цены продажи из заявочного листа (xlsx, который выгружает каталог).

    python manage.py set_prices_from_sheet "Заявочный лист ПП 13.11.2026.xlsx"          # показать
    python manage.py set_prices_from_sheet "Заявочный лист ПП 13.11.2026.xlsx" --apply  # записать

Нужна, чтобы вернуть цены, утверждённые бухгалтерией (лист ушёл в приказ),
после того как их сдвинул пересчёт. Блюдо ищется по артикулу (колонка
«Артикул»), цена — из колонки «Цена прод.». Цена ставится как обычная
фиксированная (не ручная): «Пересчитать цены» в каталоге её потом обновит.
Блюда, которых нет в листе, не трогаются.
"""

from collections import Counter
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand, CommandError

from myapp.models import Product


class Command(BaseCommand):
    help = "Цены продажи из заявочного листа xlsx (по артикулу)"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Файл заявочного листа .xlsx")
        parser.add_argument("--apply", action="store_true", help="Записать (без флага — только показать)")

    def handle(self, *args, **opts):
        prices = self._read_sheet(opts["path"])
        dup = {a for a, n in Counter(
            (p.article or "").strip() for p in Product.objects.exclude(article__isnull=True)
        ).items() if n > 1}

        changed, same, missing, skipped = [], 0, [], []
        by_article = {(p.article or "").strip(): p for p in Product.objects.exclude(article__isnull=True)}
        for article, (name, price) in prices.items():
            p = by_article.get(article)
            if p is None:
                missing.append(f"{article} {name}")
                continue
            if article in dup:
                skipped.append(f"{article} {name}")
                continue
            if p.sale_price == price and not p.sale_price_manual:
                same += 1
                continue
            changed.append((p, p.sale_price, price))

        out = self.stdout.write
        out(f"В листе цен: {len(prices)}; совпадает: {same}; изменится: {len(changed)}")
        for p, old, new in changed[:15]:
            out(f"  {p.article} {p.name[:50]}: {old} → {new}")
        if missing:
            out(self.style.WARNING(f"Нет на сайте ({len(missing)}): {', '.join(missing[:10])}"))
        if skipped:
            out(self.style.WARNING(f"Артикул задвоен на сайте, пропущено: {', '.join(skipped)}"))
        out(f"Блюд на сайте вне листа (цена не меняется): "
            f"{Product.objects.exclude(article__in=prices.keys()).count()}")

        if not opts["apply"]:
            out("Ничего не записано — добавьте --apply")
            return
        for p, _old, new in changed:
            p.sale_price = new
            p.sale_price_manual = False
            p.save(update_fields=["sale_price", "sale_price_manual"])
        out(self.style.SUCCESS(f"Записано цен: {len(changed)}"))

    @staticmethod
    def _read_sheet(path) -> dict:
        """{артикул: (наименование, цена)} из листа: строка-шапка с «Артикул»
        и «Цена прод.», дальше строки блюд (группы без цены пропускаются)."""
        try:
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        except Exception as e:
            raise CommandError(f"Не открыть {path}: {e}")
        try:
            rows = list(wb.active.iter_rows(values_only=True))
        finally:
            wb.close()                      # read_only держит файл открытым
        col_art = col_price = col_name = None
        prices = {}
        for row in rows:
            cells = [str(c).strip() if c is not None else "" for c in row]
            if col_art is None:
                if "Артикул" in cells and "Цена прод." in cells:
                    col_art, col_price = cells.index("Артикул"), cells.index("Цена прод.")
                    col_name = cells.index("Наименование продукта") if "Наименование продукта" in cells else None
                continue
            article, price = cells[col_art], row[col_price]
            if not article or not isinstance(price, (int, float)):
                continue
            name = cells[col_name] if col_name is not None else ""
            prices[article] = (name, Decimal(str(price)).quantize(Decimal("0.01")))
        if col_art is None:
            raise CommandError("В файле нет строки с колонками «Артикул» и «Цена прод.»")
        return prices
