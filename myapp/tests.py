"""Права на вкладку «Рационы Claude» и карточка блюда в редакторе рациона.

Ограниченный редактор — читатель с галочкой «Может вести рационы Claude»:
правит только свои группы и рационы плюс группы, отмеченные shared_editing
(это группы ДИАБЕТ). Чужое остаётся только для чтения, остальные вкладки —
как у обычного читателя.
"""

import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    ClaudeRation, ClaudeRationGroup, ClaudeRationSlot,
    MealCategory, MealTime, Material, Product, UserRights,
)
from .roles import READERS_GROUP, can_edit_claude_group, can_edit_claude_ration


class ClaudeEditorRightsTests(TestCase):
    def setUp(self):
        readers, _ = Group.objects.get_or_create(name=READERS_GROUP)

        self.limited = User.objects.create_user("roman", password="x")
        self.limited.groups.add(readers)
        UserRights.objects.create(user=self.limited, can_edit_claude_rations=True)

        self.plain_reader = User.objects.create_user("saule", password="x")
        self.plain_reader.groups.add(readers)

        self.editor = User.objects.create_user("adil", password="x")  # не читатель

        self.diabet = ClaudeRationGroup.objects.create(
            name="ДИАБЕТ 1800", shared_editing=True,
        )
        self.foreign = ClaudeRationGroup.objects.create(name="Рационы 1200 (тест)")
        self.own = ClaudeRationGroup.objects.create(
            name="Моя группа", created_by=self.limited,
        )

        self.foreign_ration = ClaudeRation.objects.create(
            group=self.foreign, name="Чужой рацион", kcal_category=1200,
        )
        self.own_ration = ClaudeRation.objects.create(
            group=self.own, name="Свой рацион", kcal_category=1200,
            created_by=self.limited,
        )
        self.diabet_ration = ClaudeRation.objects.create(
            group=self.diabet, name="Диабет рацион", kcal_category=1800,
        )

    # ── правила доступа ──────────────────────────────────────────────────────

    def test_limited_editor_scope(self):
        self.assertTrue(can_edit_claude_group(self.limited, self.diabet))
        self.assertTrue(can_edit_claude_group(self.limited, self.own))
        self.assertFalse(can_edit_claude_group(self.limited, self.foreign))

        self.assertTrue(can_edit_claude_ration(self.limited, self.own_ration))
        self.assertTrue(can_edit_claude_ration(self.limited, self.diabet_ration))
        self.assertFalse(can_edit_claude_ration(self.limited, self.foreign_ration))

    def test_plain_reader_has_no_access(self):
        self.assertFalse(can_edit_claude_group(self.plain_reader, self.diabet))
        self.assertFalse(can_edit_claude_ration(self.plain_reader, self.diabet_ration))

    def test_editor_edits_everything_including_limited_editors_work(self):
        for group in (self.diabet, self.foreign, self.own):
            self.assertTrue(can_edit_claude_group(self.editor, group))
        for ration in (self.own_ration, self.foreign_ration, self.diabet_ration):
            self.assertTrue(can_edit_claude_ration(self.editor, ration))

    # ── запросы ──────────────────────────────────────────────────────────────

    def test_limited_editor_cannot_touch_foreign_ration(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_ration_delete", args=[self.foreign_ration.pk])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(ClaudeRation.objects.filter(pk=self.foreign_ration.pk).exists())

    def test_limited_editor_deletes_own_ration(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_ration_delete", args=[self.own_ration.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ClaudeRation.objects.filter(pk=self.own_ration.pk).exists())

    def test_limited_editor_edits_diabet_group(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_group_edit", args=[self.diabet.pk]),
            {"name": "ДИАБЕТ 1800 (правка)", "description": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.diabet.refresh_from_db()
        self.assertEqual(self.diabet.name, "ДИАБЕТ 1800 (правка)")

    def test_limited_editor_cannot_edit_foreign_group(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_group_edit", args=[self.foreign.pk]),
            {"name": "Переименовал чужое", "description": ""},
        )
        self.assertEqual(resp.status_code, 403)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.name, "Рационы 1200 (тест)")

    def test_created_group_belongs_to_author(self):
        self.client.force_login(self.limited)
        self.client.post(reverse("claude_group_create"), {"name": "Новая", "description": ""})
        created = ClaudeRationGroup.objects.get(name="Новая")
        self.assertEqual(created.created_by, self.limited)
        self.assertTrue(can_edit_claude_group(self.limited, created))

    def test_plain_reader_blocked_by_middleware(self):
        self.client.force_login(self.plain_reader)
        resp = self.client.post(reverse("claude_group_create"), {"name": "Нельзя"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ClaudeRationGroup.objects.filter(name="Нельзя").exists())

    def test_limited_editor_still_blocked_outside_claude(self):
        """Право открывает только вкладку Claude — калоражи остаются закрыты."""
        self.client.force_login(self.limited)
        resp = self.client.post(reverse("calorie_create"), {"name": "1300", "kcal": 1300})
        self.assertEqual(resp.status_code, 403)

    def test_limited_editor_cannot_move_foreign_ration(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_ration_reorder"),
            data={
                "ration_id": self.foreign_ration.pk,
                "target_group_id": self.own.pk,
                "ordered_ids": [self.foreign_ration.pk],
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.foreign_ration.refresh_from_db()
        self.assertEqual(self.foreign_ration.group_id, self.foreign.pk)


class JktCategoryTests(TestCase):
    """Категория «ЖКТ» и её сопоставление с группой внешнего меню iiko."""

    IIKO_GROUP = "ЖКТ (желудочно кишечный тракт)"

    def test_category_seeded_by_migration(self):
        from .models import IikoCategoryMap, MealCategory

        category = MealCategory.objects.get(key="jkt")
        self.assertEqual(str(category), "ЖКТ")
        self.assertEqual(
            IikoCategoryMap.objects.get(iiko_name=self.IIKO_GROUP).slot_key, "jkt"
        )

    def test_sync_maps_iiko_group_to_jkt(self):
        from .iiko_sync import _build_label_to_key, _pick_category

        cat_display, slot_key = _pick_category(
            {"category_names": [self.IIKO_GROUP]}, _build_label_to_key()
        )
        self.assertEqual(slot_key, "jkt")
        self.assertEqual(cat_display, self.IIKO_GROUP)

    def test_catalog_filter_finds_jkt_dishes(self):
        from .models import MealCategory

        user = User.objects.create_user("adil", password="x")
        dish = Product.objects.create(name="ЖКТ* Упак Винегрет (1порц)", article="11237")
        dish.meal_categories.set([MealCategory.objects.get(key="jkt")])
        Product.objects.create(name="ПП* Упак Бигус (1порц)", article="00381")

        self.client.force_login(user)
        html = self.client.get(reverse("product_list"), {"meal_category": "jkt"}).content.decode()
        self.assertIn("Винегрет", html)
        self.assertNotIn("Бигус", html)


class OrderSheetAppendixTests(TestCase):
    """Шапка «Приложение к договору поставки» в заявочном листе."""

    def _sheet(self, with_price):
        import io
        from openpyxl import load_workbook
        from .views import _build_order_sheet_xlsx

        product = Product.objects.create(
            name="ПП* Упак Блины с мясом (3шт)", article="29272",
            packing="порц", sale_price=Decimal("921"),
        )
        resp = _build_order_sheet_xlsx([product], with_price=with_price)
        return load_workbook(io.BytesIO(resp.content)).active

    def test_without_price_is_appendix_1(self):
        ws = self._sheet(with_price=False)
        self.assertEqual(ws["C1"].value, "ПРИЛОЖЕНИЕ № 1")
        self.assertTrue(ws["C1"].font.bold)
        self.assertEqual(ws["C2"].value, "к Договору поставки № ______")
        self.assertEqual(ws["C3"].value, "от «____» __________ 20___ г.")
        self.assertEqual(ws["C1"].alignment.horizontal, "right")
        # тянется до последней колонки «ИТОГО»
        self.assertIn("C1:D1", [str(r) for r in ws.merged_cells.ranges])

    def test_with_price_is_appendix_2(self):
        ws = self._sheet(with_price=True)
        self.assertEqual(ws["C1"].value, "ПРИЛОЖЕНИЕ № 2")
        self.assertIn("C1:E1", [str(r) for r in ws.merged_cells.ranges])

    def test_existing_header_stays_in_place(self):
        """Шапка приложения не сдвигает строки ручного файла."""
        ws = self._sheet(with_price=True)
        self.assertEqual(ws["A1"].value, 1)
        self.assertEqual(ws["B1"].value, 'Заявочный лист "Фуд завод"')
        self.assertEqual(ws["B4"].value, "O-Live")
        self.assertEqual(ws["A8"].value, "Артикул")
        self.assertEqual(ws["D8"].value, "Цена прод.")
        self.assertEqual(ws["A11"].value, "29272")


class ClaudeCatalogTests(TestCase):
    """Каталог, который уходит в Claude при сборке рациона."""

    def test_catalog_carries_composition(self):
        """Без состава нельзя выполнить «без сахара»: по названию не видно."""
        from .claude_rations import _build_catalog

        # composition_clean не задаём: он пересчитывается из сырого состава
        # в Product.save() по справочнику ингредиентов
        product = Product.objects.create(
            name="ПП* Упак Поке боул с уткой (1порц)",
            composition="Киноа, утиное филе, сахар, соус ореховый",
            kcal_per_serving=Decimal("520"),
        )
        row = _build_catalog([product])[0]
        self.assertIn("ахар", row["composition"])     # «Сахар» после очистки
        self.assertEqual(row["id"], product.pk)

    def test_catalog_falls_back_to_raw_composition(self):
        from .claude_rations import _build_catalog

        product = Product.objects.create(
            name="Блюдо без чистого состава", composition="Сырой состав из iiko",
        )
        self.assertEqual(_build_catalog([product])[0]["composition"], "Сырой состав из iiko")


class MarkupTests(TestCase):
    """Наценка: 67% на блюда и смузи, 15% на напитки («Доп. товары»), вверх до тенге.
    Цена фиксированная: ставится новому блюду, дальше меняется только reprice()."""

    def test_dish_gets_67_percent(self):
        p = Product.objects.create(name="Салат", cost=Decimal("396"))
        self.assertEqual(p.sale_price, Decimal("662"))        # 661.32 -> 662
        self.assertFalse(p.markup_is_low)

    def test_cost_change_keeps_price_until_reprice(self):
        # себестоимость из O·ERP плавает — цена в заявочном листе не должна
        p = Product.objects.create(name="Салат", cost=Decimal("396"))
        p.cost = Decimal("500")
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.sale_price, Decimal("662"))
        self.assertTrue(p.reprice())
        self.assertEqual(p.sale_price, Decimal("835"))        # 500 * 1.67
        self.assertFalse(p.reprice())                         # уже по наценке

    def test_drink_reprice_uses_15_percent(self):
        extra, _ = MealCategory.objects.get_or_create(key="extra")
        p = Product.objects.create(name="Боржоми", cost=Decimal("644"))
        self.assertEqual(p.sale_price, Decimal("1076"))       # без категории — блюдо, 67%
        p.meal_categories.set([extra])
        self.assertTrue(p.reprice())
        self.assertEqual(p.sale_price, Decimal("741"))        # 740.6 -> 741
        self.assertFalse(p.markup_is_low)                     # 15% для напитка — норма

    def test_smoothie_gets_67_percent(self):
        smoothie, _ = MealCategory.objects.get_or_create(key="smoothie")
        p = Product.objects.create(name="Смузи", cost=Decimal("300"))
        p.meal_categories.set([smoothie])
        p.reprice()
        self.assertEqual(p.sale_price, Decimal("501"))        # 300 * 1.67

    def test_custom_markup_from_price(self):
        # прайс: термопакет 154 ₸ при себестоимости 152.80 — наценка 0.785…%
        p = Product.objects.create(name="Термопакет", cost=Decimal("152.80"), sale_price=Decimal("154"))
        self.assertTrue(p.lock_markup_from_price())
        p.save()
        self.assertFalse(p.reprice())                         # та же себестоимость — та же цена
        self.assertEqual(p.sale_price, Decimal("154"))
        p.cost = Decimal("160")                               # себестоимость выросла
        p.save()
        self.assertTrue(p.markup_is_low)                      # цена отстала от своей наценки
        self.assertTrue(p.reprice())
        self.assertEqual(p.sale_price, Decimal("162"))        # 160 × 1.00785… = 161.26 → вверх
        self.assertFalse(p.markup_is_low)

    def test_negative_custom_markup_kept(self):
        # одноразовый набор продаётся ниже себестоимости: 29 ₸ при 36.72
        p = Product.objects.create(name="Набор", cost=Decimal("36.72"), sale_price=Decimal("29"))
        p.lock_markup_from_price(); p.save()
        self.assertLess(p.custom_markup_pct, 0)
        self.assertFalse(p.reprice())
        self.assertEqual(p.sale_price, Decimal("29"))
        p.cost = Decimal("40")
        p.reprice()
        self.assertEqual(p.sale_price, Decimal("32"))         # 40 × 0.7897… = 31.59 → вверх

    def test_material_price_in_order_sheet(self):
        import io
        import openpyxl
        from .views import _build_order_sheet_xlsx
        cat, _ = MealCategory.objects.get_or_create(key="materials")
        Material.objects.create(article="27602", name="У* Термопакет серый", unit="1 шт")
        p = Product.objects.create(name="У* Термопакет серый", article="27602",
                                   cost=Decimal("152.8"), sale_price=Decimal("154"))
        p.meal_categories.set([cat])
        ws = openpyxl.load_workbook(io.BytesIO(_build_order_sheet_xlsx([], with_price=True).content)).active
        row = next(r for r in ws.iter_rows(values_only=True) if r[0] == "27602")
        self.assertEqual(row[3], 154)

    def test_lock_markup_from_price_list(self):
        import io, os, tempfile
        import openpyxl
        from django.core.management import call_command
        cat, _ = MealCategory.objects.get_or_create(key="materials")
        bag = Product.objects.create(name="У* Термопакет", article="27605", cost=Decimal("172.44"))
        dish = Product.objects.create(name="Суп", article="44928", cost=Decimal("300"))
        bag.meal_categories.set([cat])
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append([None, None, "АССОРТИМЕНТ И СТОИМОСТЬ ТОВАРА"])
        ws.append(["Артикул", "ШК ", "Наименование товара", "Срок годности",
                   "Цена в тенге, \nв т.ч. НДС (отпускная)"])
        ws.append([44928, None, "Суп", None, 537])
        ws.append(["Материалы", None, None, None, None])
        ws.append([27605, None, "У* Термопакет", None, "172"])
        fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
        try:
            wb.save(path)
            call_command("set_prices_from_sheet", path, "--category", "materials",
                         "--lock-markup", "--apply", stdout=io.StringIO())
        finally:
            os.remove(path)
        bag.refresh_from_db(); dish.refresh_from_db()
        self.assertEqual(bag.sale_price, Decimal("172"))
        self.assertLess(bag.custom_markup_pct, 0)             # 172 < 172.44
        self.assertFalse(bag.reprice())                       # пересчёт даёт ту же цену
        self.assertEqual(dish.sale_price, Decimal("501"))     # не материал — не тронут
        self.assertIsNone(dish.custom_markup_pct)

    def test_reprice_keeps_manual_price(self):
        p = Product.objects.create(name="Вода", cost=Decimal("100"),
                                   sale_price=Decimal("150"), sale_price_manual=True)
        self.assertFalse(p.reprice())
        self.assertEqual(p.sale_price, Decimal("150"))

    def test_cleared_price_is_set_by_markup(self):
        p = Product.objects.create(name="Салат", cost=Decimal("396"),
                                   sale_price=Decimal("700"), sale_price_manual=True)
        p.sale_price, p.sale_price_manual = None, False       # очистили поле в каталоге
        p.save()
        self.assertEqual(p.sale_price, Decimal("662"))

    def test_reprice_button(self):
        admin = User.objects.create_superuser("boss", password="x")
        auto = Product.objects.create(name="Салат", cost=Decimal("396"))
        manual = Product.objects.create(name="Вода", cost=Decimal("100"),
                                        sale_price=Decimal("150"), sale_price_manual=True)
        Product.objects.filter(pk=auto.pk).update(cost=Decimal("500"))
        self.client.force_login(admin)
        resp = self.client.post(reverse("products_reprice"))
        self.assertEqual(resp.json()["changed"], 1)
        auto.refresh_from_db(); manual.refresh_from_db()
        self.assertEqual(auto.sale_price, Decimal("835"))
        self.assertEqual(manual.sale_price, Decimal("150"))

    def test_reprice_selected_only(self):
        admin = User.objects.create_superuser("boss", password="x")
        a = Product.objects.create(name="Салат", cost=Decimal("396"))
        b = Product.objects.create(name="Суп", cost=Decimal("300"))
        manual = Product.objects.create(name="Вода", cost=Decimal("100"),
                                        sale_price=Decimal("150"), sale_price_manual=True)
        Product.objects.filter(pk__in=[a.pk, b.pk]).update(cost=Decimal("500"))
        self.client.force_login(admin)
        resp = self.client.post(reverse("products_reprice"),
                                data=json.dumps({"ids": [a.pk, manual.pk]}),
                                content_type="application/json")
        self.assertEqual(resp.json()["changed"], 2)
        a.refresh_from_db(); b.refresh_from_db(); manual.refresh_from_db()
        self.assertEqual(a.sale_price, Decimal("835"))
        self.assertEqual(b.sale_price, Decimal("501"))        # не выбран — без изменений
        self.assertEqual(manual.sale_price, Decimal("167"))   # выбран явно — по наценке
        self.assertFalse(manual.sale_price_manual)

    def test_reprice_preview(self):
        admin = User.objects.create_superuser("boss", password="x")
        p = Product.objects.create(name="Салат", article="00772", cost=Decimal("396"))
        Product.objects.filter(pk=p.pk).update(cost=Decimal("785"))
        self.client.force_login(admin)
        row = self.client.get(reverse("products_reprice_preview")).json()["products"][0]
        self.assertEqual((row["price"], row["new_price"]), (662.0, 1311.0))
        self.assertTrue(row["low"])                           # наценка < 40% — красная
        self.assertEqual(Product.objects.get(pk=p.pk).sale_price, Decimal("662"))

    def test_catalog_scripts_parse(self):
        """Скрипты каталога без синтаксических ошибок: одна такая (перенос строки
        внутри строки JS) уже роняла все кнопки каталога."""
        import re, shutil, subprocess, tempfile, os
        node = shutil.which("node")
        if not node:
            self.skipTest("нет node")
        self.client.force_login(User.objects.create_superuser("boss", password="x"))
        html = self.client.get(reverse("product_list")).content.decode()
        for block in re.findall(r"<script>(.*?)</script>", html, re.S):
            fd, path = tempfile.mkstemp(suffix=".js")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(block)
            try:
                res = subprocess.run([node, "--check", path], capture_output=True, text=True)
            finally:
                os.remove(path)
            self.assertEqual(res.returncode, 0, res.stderr[:500])

    def test_reprice_button_closed_to_plain_reader(self):
        readers, _ = Group.objects.get_or_create(name=READERS_GROUP)
        reader = User.objects.create_user("reader", password="x")
        reader.groups.add(readers)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(reverse("products_reprice")).status_code, 403)

    def test_prices_from_order_sheet(self):
        import io, os, tempfile
        import openpyxl
        from django.core.management import call_command
        p = Product.objects.create(name="Салат", article="00772", cost=Decimal("792"))
        other = Product.objects.create(name="Суп", article="00100", cost=Decimal("300"))
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(["Компания", "O-Live"])
        ws.append(["Артикул", "Наименование продукта", "Кратность заказа", "Цена прод.", "ИТОГО"])
        ws.append(["Здоровое Питание", None, None, None, None])
        ws.append(["00772", "Салат", "1 порц", 1320, None])
        ws.append(["99999", "Нет на сайте", "1 порц", 100, None])
        fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
        try:
            wb.save(path)
            call_command("set_prices_from_sheet", path, stdout=io.StringIO())
            p.refresh_from_db()
            self.assertEqual(p.sale_price, Decimal("1323"))   # без --apply не пишет
            call_command("set_prices_from_sheet", path, "--apply", stdout=io.StringIO())
        finally:
            os.remove(path)
        p.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(p.sale_price, Decimal("1320"))
        self.assertFalse(p.sale_price_manual)
        self.assertEqual(other.sale_price, Decimal("501"))    # вне листа — без изменений


class ProductCardTests(TestCase):
    """Карточка блюда, которую открывает клик по блюду в слоте рациона."""

    def setUp(self):
        self.user = User.objects.create_user("adil", password="x")
        self.product = Product.objects.create(
            name="ПП* Упак Блины с мясом (3шт)", article="29272",
            iiko_category="ПП* ЗАВТРАК", net_weight=Decimal("0.265"),
            cost=Decimal("551"), sale_price=Decimal("921"),
            composition="Мука, молоко, фарш говяжий, яйцо, соль",
            protein_per_serving=Decimal("25.1"), fat_per_serving=Decimal("28.2"),
            carbs_per_serving=Decimal("35.0"), kcal_per_serving=Decimal("494"),
            protein=Decimal("9.5"), fat=Decimal("10.6"),
            carbs=Decimal("13.2"), kcal_per_100=Decimal("186"),
        )

    def test_card_returns_full_info(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("product_card", args=[self.product.pk]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "ПП* Упак Блины с мясом (3шт)")
        self.assertEqual(data["article"], "29272")
        self.assertIn("фарш говяжий", data["composition"])
        self.assertNotIn("allergens", data)      # аллергены с платформы убраны
        self.assertEqual(data["weight_g"], 265.0)      # кг из базы -> граммы
        self.assertEqual(data["sale_price"], 921.0)    # 551 + наценка 67%, вверх
        self.assertEqual(data["per_serving"]["kcal"], 494.0)
        self.assertEqual(data["per_100"]["kcal"], 186.0)

    def test_card_needs_login(self):
        resp = self.client.get(reverse("product_card", args=[self.product.pk]))
        self.assertEqual(resp.status_code, 302)        # уводит на /login/

    def test_ration_editor_makes_dish_clickable(self):
        group = ClaudeRationGroup.objects.create(name="ДИАБЕТ 2200")
        ration = ClaudeRation.objects.create(
            group=group, name="Диабет 2200 день 7", kcal_category=2200,
        )
        ClaudeRationSlot.objects.create(
            ration=ration, product=self.product, slot_type="breakfast",
            meal_time=MealTime.objects.create(name="Завтрак-1"),
        )
        self.client.force_login(self.user)
        html = self.client.get(
            reverse("claude_ration_edit", args=[ration.pk])
        ).content.decode()
        self.assertIn(f"openDishModal({self.product.pk})", html)


@override_settings(EXPORT_API_TOKEN="secret-token", EXPORT_PUBLIC_BASE_URL="https://olive-nutri-baza.kz")
class ExportApiTests(TestCase):
    """GET /api/export/ — выгрузка всей базы для общей базы в Supabase."""

    def setUp(self):
        self.url = reverse("export_all")
        self.product = Product.objects.create(
            name="Суп-пюре тыквенный", article="30001",
            net_weight=Decimal("0.300"), cost=Decimal("300"),
            kcal_per_100=Decimal("55"), composition="Тыква, сливки",
        )
        User.objects.create_user("adil", password="x")
        meal = MealTime.objects.create(name="Обед")
        group = ClaudeRationGroup.objects.create(name="ДИАБЕТ 1800")
        ration = ClaudeRation.objects.create(group=group, name="День 1", kcal_category=1800)
        ClaudeRationSlot.objects.create(
            ration=ration, meal_time=meal, slot_type="soup", product=self.product,
        )

    def get(self, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(self.url, **headers)

    def test_needs_token(self):
        self.assertEqual(self.get().status_code, 401)
        self.assertEqual(self.get("wrong").status_code, 401)

    @override_settings(EXPORT_API_TOKEN="")
    def test_disabled_without_configured_token(self):
        self.assertEqual(self.get("").status_code, 503)
        self.assertEqual(self.get("anything").status_code, 503)

    def test_exports_all_tables(self):
        resp = self.get("secret-token")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["counts"]["products"], 1)

        product = data["products"][0]
        self.assertEqual(product["net_weight_g"], 300.0)       # кг из базы -> граммы
        self.assertEqual(product["sale_price"], 501.0)          # автонаценка 67%
        self.assertEqual(product["kcal_100"], 55.0)

        slot = data["ration_slots"][0]
        self.assertEqual(slot["product_id"], product["id"])
        self.assertEqual(data["rations"][0]["kcal"], 1800)
        self.assertIn("soup", {c["key"] for c in data["meal_categories"]})

    def test_no_user_data_leaks(self):
        body = self.get("secret-token").content.decode()
        self.assertNotIn("password", body)
        self.assertNotIn("users", self.get("secret-token").json())

    def test_post_not_allowed(self):
        resp = self.client.post(self.url, HTTP_AUTHORIZATION="Bearer secret-token")
        self.assertEqual(resp.status_code, 405)


class SyncNetWeightTests(TestCase):
    """Масса нетто — из карточки iiko Server (unitWeight), а не из веса порции
    внешнего меню: там бывает вес с тарой."""

    PID = "3f8f2ba7-b29e-4a2b-8ca1-c1250eb87504"

    def _run_sync(self, unit_weight):
        from unittest import mock
        from myapp import iiko_sync

        menu = {"itemCategories": [{"name": "ПП* ЗАВТРАК", "items": [{
            "itemId": self.PID, "name": "Баклажан пармиджано", "sku": "00516",
            "itemSizes": [{
                "portionWeightGrams": 380,
                "nutritionPerHundredGrams": {
                    "energy": 100, "proteins": 5, "fats": 4, "carbs": 10,
                },
            }],
        }]}]}
        cloud = mock.Mock()
        cloud.get_menu_by_id.return_value = menu
        cloud.get_nomenclature.return_value = {"products": []}
        server = mock.Mock()
        server.get_products.return_value = [{
            "id": self.PID, "num": "00516", "name": "ПП* Упак Баклажан пармиджано",
            "unitWeight": unit_weight,
            "containers": [{"fullContainerWeight": 0.38}],
        }]
        server.get_assembly_tree.return_value = []
        server.get_cost_report.return_value = {}

        iiko_sync._last_sync_time = 0
        with mock.patch.object(iiko_sync, "IikoCloudClient", return_value=cloud), \
             mock.patch.object(iiko_sync, "IikoServerClient", return_value=server):
            res = iiko_sync.sync_products_from_iiko(
                "key", "org", "menu", "http://srv", "login", "pass")
        self.assertEqual(res["errors"], [])
        return Product.objects.get(iiko_id=self.PID)

    def test_weight_and_per_serving_from_server_card(self):
        p = self._run_sync(0.32)
        self.assertEqual(p.net_weight, Decimal("0.320"))
        self.assertEqual(float(p.kcal_per_serving), 320.0)
        self.assertEqual(float(p.protein_per_serving), 16.0)

    def test_fallback_to_menu_weight_without_unit_weight(self):
        p = self._run_sync(0)
        self.assertEqual(p.net_weight, Decimal("0.380"))
        self.assertEqual(float(p.kcal_per_serving), 380.0)

    def test_fractional_unit_weight_rounded_half_up(self):
        p = self._run_sync(0.2865)
        self.assertEqual(p.net_weight, Decimal("0.287"))


class OerpSyncTests(TestCase):
    """Загрузка блюд из O·ERP (myapp/oerp_sync.py) на ответах в формате export-API."""

    ROOT, BREAKFAST, BREAKFAST_EMPTY, NESTED, DRINKS, FMD = (
        "g-root", "g-breakfast", "g-breakfast-empty", "g-nested", "g-drinks", "g-fmd")

    GROUPS = [
        {"id": "g-gp", "parentId": None, "name": "Фудзавод ГП", "deleted": False},
        {"id": ROOT, "parentId": "g-gp", "name": "ЗДОРОВОЕ ПИТАНИЕ", "deleted": False},
        {"id": BREAKFAST, "parentId": ROOT, "name": "1ПП* ЗАВТРАК", "deleted": False},
        {"id": BREAKFAST_EMPTY, "parentId": ROOT, "name": "1ПП* ЗАВТРАК", "deleted": False},
        {"id": NESTED, "parentId": BREAKFAST, "name": "Сырники", "deleted": False},
        {"id": DRINKS, "parentId": ROOT, "name": "ПП* ДОП.ТОВАРЫ", "deleted": False},
        {"id": FMD, "parentId": ROOT, "name": "ФМД (диета)", "deleted": False},
    ]

    DISH = {
        "id": "d-1", "code": "00516", "name": "ПП* Упак Каша овсяная", "kind": "dish",
        "groupId": NESTED, "deleted": False, "baseUomName": "порц",
        "unitWeightKg": "0.320000000", "description": None,
        "nutrition": {"per100g": {"kcal": "150", "protein": "5.5", "fat": "3", "carbs": "25"},
                      "perUnit": None},
    }
    DRINK = {
        "id": "w-1", "code": "00900", "name": "С* Вода Боржоми 0,5", "kind": "goods",
        "groupId": DRINKS, "deleted": False, "baseUomName": "шт",
        "unitWeightKg": "0.500", "description": None, "nutrition": None,
    }
    FMD_DISH = dict(DISH, id="f-1", code="07000", name="ФМД суп", groupId=FMD)

    TECH_CARDS = [
        {"productId": "d-1", "code": "00516", "name": "Каша", "dateFrom": "2026-01-01", "dateTo": None,
         "items": [
             # выход 0 текстом — берём нетто, как у iiko
             {"productId": "p-base", "name": "П* Основа каши", "amountIn": "0.3",
              "amountMiddle": "0.3", "amountOut": "0.000"},
             {"productId": "u-box", "name": "У* Контейнер", "amountIn": "1",
              "amountMiddle": "1", "amountOut": "1"},
         ]},
        {"productId": "p-base", "code": "P1", "name": "Основа каши", "dateFrom": "2026-01-01", "dateTo": None,
         "items": [
             {"productId": "r-oat", "name": "С* Хлопья овсяные", "amountIn": "0.1",
              "amountMiddle": "0.1", "amountOut": "0.1"},
             {"productId": "r-milk", "name": "С* Молоко 3,2%", "amountIn": "0.2",
              "amountMiddle": "0.2", "amountOut": "0.2"},
         ]},
    ]

    def setUp(self):
        for key in ("breakfast", "extra", "fmd"):
            MealCategory.objects.get_or_create(key=key)
        self.costs = [
            {"id": "d-1", "code": "00516", "ssnCurrent": "396.004", "ssnpp": "420",
             "spp": "405", "ssn": "390", "ssc": "410.5", "kind": "dish"},
        ]
        # у товаров O·ERP ССН не считает — первое непустое по порядку (здесь СПП)
        self.goods_costs = [{"id": "w-1", "code": "00900", "ssnCurrent": None, "ssnpp": None,
                             "spp": "452", "ssn": None, "ssc": "460", "kind": "goods"}]

    def _fetch(self, resource, page_size, **params):
        if resource == "groups":
            return self.GROUPS
        if resource == "products":
            return {"dish": [self.DISH, self.FMD_DISH],
                    "goods": [self.DRINK] + getattr(self, "extra_goods", [])}[params["kind"]]
        if resource == "tech-cards":
            return self.TECH_CARDS
        if resource == "dish-costs":
            return self.goods_costs if params.get("kind") == "goods" else self.costs
        raise AssertionError(resource)

    def _sync(self):
        from unittest.mock import patch
        from .oerp_sync import OerpClient, sync_products_from_oerp
        with patch.object(OerpClient, "fetch_all", self._fetch):
            return sync_products_from_oerp("erpk_test")

    def test_materials_from_materials_tab(self):
        # термопакет лежит в O·ERP вне «ЗДОРОВОЕ ПИТАНИЕ» — берём по артикулу вкладки «Материалы»
        MealCategory.objects.get_or_create(key="materials")
        Material.objects.create(article="27602", name="У* Термопакет серый 28*28*20")
        self.extra_goods = [{
            "id": "m-1", "code": "27602", "name": "У* Термопакет серый 28*28*20", "kind": "goods",
            "groupId": "g-packaging", "deleted": False, "baseUomName": "шт",
            "unitWeightKg": None, "description": None, "nutrition": None,
        }, dict(self.DRINK, id="x-1", code="55555", groupId="g-other", name="Чужой товар")]
        self.goods_costs = self.goods_costs + [
            {"id": "m-1", "code": "27602", "ssnCurrent": None, "ssnpp": None,
             "spp": "152.8", "ssn": None, "ssc": "152.8", "kind": "goods"}]
        self._sync()
        p = Product.objects.get(article="27602")
        self.assertEqual(list(p.meal_categories.values_list("key", flat=True)), ["materials"])
        self.assertEqual(p.iiko_category, "Материалы")
        self.assertEqual(p.cost, Decimal("152.80"))
        self.assertEqual(p.sale_price, Decimal("176"))         # материал — 15%: 152.8 × 1.15 = 175.72
        self.assertFalse(Product.objects.filter(article="55555").exists())

    def test_cost_order_ssn_current_first(self):
        from .oerp_sync import _pick_cost
        row = {"ssnCurrent": "300", "ssnpp": "310", "spp": "320", "ssn": "330", "ssc": "340"}
        self.assertEqual(_pick_cost(row), (300.0, "ssnCurrent"))
        row["ssnCurrent"] = None
        self.assertEqual(_pick_cost(row), (310.0, "ssnpp"))
        row["ssnpp"] = None
        self.assertEqual(_pick_cost(row), (320.0, "spp"))
        row["spp"] = None
        self.assertEqual(_pick_cost(row), (330.0, "ssn"))
        row["ssn"] = None
        self.assertEqual(_pick_cost(row), (340.0, "ssc"))
        row["ssc"] = None
        self.assertEqual(_pick_cost(row), (None, None))

    def test_folder_names_match_iiko_menu_categories(self):
        from .oerp_sync import _category_map, _folder_key
        cmap = _category_map()
        self.assertEqual(cmap[_folder_key("1ПП* ЗАВТРАК")], "breakfast")
        self.assertEqual(cmap[_folder_key("3ПП* ГОРЯЧЕЕ 400-500 ккал")], "hot_400")
        self.assertEqual(cmap[_folder_key("ПП* ДОП.ТОВАРЫ")], "extra")   # в iiko «ПП* Доп. товары»
        self.assertEqual(cmap[_folder_key("ФМД (диета)")], "fmd")

    def test_sync_creates_dishes_from_mapped_folders_only(self):
        result = self._sync()
        self.assertEqual(result["created"], 3)                 # ФМД — своя категория
        fmd = Product.objects.get(iiko_id="f-1")
        self.assertEqual(fmd.iiko_category, "ФМД (диета)")
        self.assertEqual(list(fmd.meal_categories.values_list("key", flat=True)), ["fmd"])

        p = Product.objects.get(iiko_id="d-1")
        self.assertEqual(p.article, "00516")
        self.assertEqual(p.iiko_category, "ПП* ЗАВТРАК")       # без цифры порядка
        self.assertEqual(list(p.meal_categories.values_list("key", flat=True)), ["breakfast"])
        self.assertEqual(p.net_weight, Decimal("0.320"))
        self.assertEqual(float(p.kcal_per_serving), 480.0)     # 150 × 320 / 100
        self.assertEqual(p.composition, "Молоко 3,2%, Хлопья овсяные")
        self.assertEqual(p.cost, Decimal("396.00"))            # ССН' (ssnCurrent)
        self.assertEqual(p.sale_price, Decimal("662"))         # 67%

        drink = Product.objects.get(iiko_id="w-1")
        self.assertEqual(list(drink.meal_categories.values_list("key", flat=True)), ["extra"])
        self.assertEqual(drink.sale_price, Decimal("520"))     # 452 × 1.15 = 519.8 → вверх

    def test_resync_updates_by_article_and_keeps_cost_when_not_calculated(self):
        Product.objects.create(name="Старое имя", article="00516", iiko_id="old-guid",
                               cost=Decimal("380"))
        self.costs = [{"id": "d-1", "code": "00516", "ssnCurrent": None, "ssnpp": None,
                       "spp": None, "ssn": None, "ssc": None, "kind": "dish"}]
        result = self._sync()
        self.assertEqual(result["updated"], 1)
        p = Product.objects.get(article="00516")
        self.assertEqual(p.name, "ПП* Упак Каша овсяная")
        self.assertEqual(p.cost, Decimal("380"))               # null из O·ERP — не 0

    def test_resync_new_cost_keeps_fixed_price(self):
        self._sync()
        self.costs = [{"id": "d-1", "code": "00516", "ssnCurrent": "500", "kind": "dish"}]
        self._sync()
        p = Product.objects.get(iiko_id="d-1")
        self.assertEqual(p.cost, Decimal("500.00"))
        self.assertEqual(p.sale_price, Decimal("662"))         # цена с первой загрузки

    def test_compare_reports_differences_without_writing(self):
        from unittest.mock import patch
        from .oerp_sync import OerpClient, collect_from_oerp, compare_with_db
        Product.objects.create(name="ПП* Упак Каша овсяная", article="00516", iiko_id="d-1",
                               cost=Decimal("350"))
        with patch.object(OerpClient, "fetch_all", self._fetch):
            report = compare_with_db(collect_from_oerp(OerpClient("erpk_test")))
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["same_id"], 1)
        self.assertEqual(sorted(report["new"]), ["С* Вода Боржоми 0,5", "ФМД суп"])
        self.assertEqual([d[3] for d in report["diffs"]["cost"]], [Decimal("396.00")])
        self.assertEqual(report["diffs"]["name"], [])
        self.assertEqual(Product.objects.get(article="00516").cost, Decimal("350"))


class PriceListTests(TestCase):
    """Прайс «Приложение №2» — заявочный лист с галочкой «цена»."""

    def _rows(self, response):
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        return ws, [tuple(c.value for c in r[:5]) for r in ws.iter_rows()]

    def test_price_list_layout(self):
        from .models import SwapGroup, SwapItem
        from .views import _build_price_list_xlsx
        cats = {k: MealCategory.objects.get_or_create(key=k)[0]
                for k in ("breakfast", "soup", "materials")}
        pancakes = Product.objects.create(name="ПП* Упак Панкейки", article="00792", cost=Decimal("600"))
        pancakes.meal_categories.set([cats["breakfast"]])
        borsch = Product.objects.create(name="ПП* Упак Борщ", article="44928", cost=Decimal("300"))
        borsch.meal_categories.set([cats["soup"]])
        vip = SwapGroup.objects.create(name="Блюда на замену VIP- завтраки", order=1)
        sport = SwapGroup.objects.create(name="Блюда на замену Sport- завтраки", order=2)
        SwapItem.objects.create(swap_group=vip, product=pancakes)
        SwapItem.objects.create(swap_group=sport, product=borsch)
        Material.objects.create(article="96374", name="С* Вода Esen")
        water = Product.objects.create(name="С* Вода Esen", article="96374", cost=Decimal("192"))
        water.meal_categories.set([cats["materials"]])
        water.reprice(); water.save()                              # как синхронизация после категории

        resp = _build_price_list_xlsx([borsch, pancakes], [vip, sport])
        from urllib.parse import unquote
        self.assertIn("Приложение №2 ПП ", unquote(resp["Content-Disposition"]))
        ws, rows = self._rows(resp)
        self.assertEqual(len(ws._images), 1)                       # логотип
        self.assertEqual(rows[8][:5], ("Артикул", "ШК ", "Наименование товара", "Срок годности",
                                       rows[8][4]))
        self.assertTrue(rows[8][4].startswith("Цена в тенге"))
        body = [r for r in rows[35:] if any(v is not None for v in r)]
        names = [r[0] if r[2] is None else r[2] for r in body]
        self.assertEqual(names[:6], ["Завтрак", "ПП* Упак Панкейки", "Суп", "ПП* Упак Борщ",
                                     "Блюда на замену", "Завтраки"])
        self.assertEqual(names[6:10], ["VIP- завтраки", "ПП* Упак Панкейки",
                                       "Sport- завтраки", "ПП* Упак Борщ"])   # «Завтраки» — один раз
        self.assertIn(("00792", None, "ПП* Упак Панкейки", None, 1002), body)  # 600 × 1.67
        self.assertIn(("96374", None, "С* Вода Esen", None, 221), body)        # материал 15%
        flat = [v for r in body for v in r if isinstance(v, str)]
        for text in ("Материалы", "Сырье", "ОРГАНИЗАЦИЯ:", "Управляющий директор"):
            self.assertIn(text, flat)

    def test_order_sheet_view_with_price_gives_price_list(self):
        from .models import SwapGroup, SwapItem
        admin = User.objects.create_superuser("boss", password="x")
        g = SwapGroup.objects.create(name="Смузи")
        SwapItem.objects.create(swap_group=g, product=Product.objects.create(name="Смузи", cost=Decimal("300")))
        self.client.force_login(admin)
        with_price = self.client.get(reverse("claude_order_sheet"), {"swap_group": g.pk, "price": 1})
        plain = self.client.get(reverse("claude_order_sheet"), {"swap_group": g.pk})
        self.assertIn("%D0%9F%D1%80%D0%B8%D0%BB%D0%BE%D0%B6%D0%B5%D0%BD%D0%B8%D0%B5",
                      with_price["Content-Disposition"])               # «Приложение»
        self.assertIn("%D0%97%D0%B0%D1%8F%D0%B2%D0%BE%D1%87%D0%BD%D1%8B%D0%B9",
                      plain["Content-Disposition"])                    # «Заявочный»
