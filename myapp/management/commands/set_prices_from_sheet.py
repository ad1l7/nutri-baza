"""Цены продажи из заявочного листа или прайса (xlsx).

    python manage.py set_prices_from_sheet "Заявочный лист ПП 13.11.2026.xlsx"          # показать
    python manage.py set_prices_from_sheet "Заявочный лист ПП 13.11.2026.xlsx" --apply  # записать

    # прайс «Приложение №2», только материалы, наценка — из цены прайса
    python manage.py set_prices_from_sheet "Приложение №2.xlsx" --category materials --lock-markup --apply

Нужна, чтобы вернуть цены, утверждённые бухгалтерией (лист ушёл в приказ),
после того как их сдвинул пересчёт. Позиция ищется по артикулу (колонка
«Артикул»), цена — из колонки «Цена прод.» заявочного листа или «Цена …»
прайса. Цена ставится как обычная фиксированная (не ручная). Позиции, которых
нет в листе, не трогаются.

--lock-markup: заодно запомнить у позиции свою наценку = цена / себестоимость
(Product.custom_markup_pct) — «Пересчитать цены» дальше держит этот процент,
а не общие 67% / 15%.
"""

from collections import Counter
from decimal import Decimal, InvalidOperation

import openpyxl
from django.core.management.base import BaseCommand, CommandError

from myapp.models import Product


class Command(BaseCommand):
    help = "Цены продажи из заявочного листа или прайса xlsx (по артикулу)"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Файл .xlsx")
        parser.add_argument("--apply", action="store_true", help="Записать (без флага — только показать)")
        parser.add_argument("--category", help="Только позиции этой категории сайта (ключ, например materials)")
        parser.add_argument("--lock-markup", action="store_true",
                            help="Запомнить наценку из цены листа и себестоимости как свою")

    def handle(self, *args, **opts):
        prices = self._read_sheet(opts["path"])
        products = Product.objects.exclude(article__isnull=True)
        if opts["category"]:
            products = products.filter(meal_categories__key=opts["category"])
            in_scope = {(p.article or "").strip() for p in products}
            prices = {a: v for a, v in prices.items() if a in in_scope}
        products = list(products)
        dup = {a for a, n in Counter((p.article or "").strip() for p in products).items() if n > 1}

        changed, same, missing, skipped = [], 0, [], []
        by_article = {(p.article or "").strip(): p for p in products}
        for article, (name, price) in prices.items():
            p = by_article.get(article)
            if p is None:
                missing.append(f"{article} {name}")
                continue
            if article in dup:
                skipped.append(f"{article} {name}")
                continue
            if p.sale_price == price and not p.sale_price_manual and not opts["lock_markup"]:
                same += 1
                continue
            changed.append((p, p.sale_price, price))

        out = self.stdout.write
        out(f"В листе цен: {len(prices)}; совпадает: {same}; изменится: {len(changed)}")
        for p, old, new in changed[:15]:
            line = f"  {p.article} {p.name[:50]}: {old} → {new}"
            if opts["lock_markup"]:
                if p.cost:
                    pct = (new / p.cost - 1) * 100
                    line += f"  (себестоимость {p.cost}, наценка {pct:.2f}%)"
                else:
                    line += "  (нет себестоимости — наценку не запомнить)"
            out(line)
        if missing:
            out(self.style.WARNING(f"Нет на сайте ({len(missing)}): {', '.join(missing[:10])}"))
        if skipped:
            out(self.style.WARNING(f"Артикул задвоен на сайте, пропущено: {', '.join(skipped)}"))
        if not opts["category"]:
            out(f"Позиций на сайте вне листа (цена не меняется): "
                f"{Product.objects.exclude(article__in=prices.keys()).count()}")

        if not opts["apply"]:
            out("Ничего не записано — добавьте --apply")
            return
        for p, _old, new in changed:
            p.sale_price = new
            p.sale_price_manual = False
            fields = ["sale_price", "sale_price_manual"]
            if opts["lock_markup"] and p.lock_markup_from_price():
                fields.append("custom_markup_pct")
            p.save(update_fields=fields)
        out(self.style.SUCCESS(f"Записано цен: {len(changed)}"))

    @staticmethod
    def _price(value):
        """Цена из ячейки: число или текст «154» / «1 154,50»; иначе None."""
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            raw = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
            try:
                return Decimal(raw) if raw else None
            except InvalidOperation:
                return None
        return None

    @classmethod
    def _read_sheet(cls, path) -> dict:
        """{артикул: (наименование, цена)}: строка-шапка с «Артикул» и колонкой
        цены («Цена прод.» заявочного листа или «Цена в тенге…» прайса), дальше
        строки позиций (заголовки групп без цены пропускаются)."""
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
                price_cols = [i for i, c in enumerate(cells) if c.startswith("Цена")]
                if "Артикул" in cells and price_cols:
                    col_art, col_price = cells.index("Артикул"), price_cols[0]
                    col_name = next((i for i, c in enumerate(cells) if c.startswith("Наименование")), None)
                continue
            if col_price >= len(row):
                continue
            article, price = cells[col_art], cls._price(row[col_price])
            if not article or price is None:
                continue
            name = cells[col_name] if col_name is not None else ""
            prices[article] = (name, price.quantize(Decimal("0.01")))
        if col_art is None:
            raise CommandError("В файле нет строки с колонками «Артикул» и «Цена…»")
        return prices
