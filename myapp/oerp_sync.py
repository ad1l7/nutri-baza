"""
oerp_sync.py — загрузка блюд Olive из O·ERP вместо iiko.

Описание источника: docs/oerp-source.md. Коротко:
  - блюда — папка «ЗДОРОВОЕ ПИТАНИЕ» в номенклатуре O·ERP, её подпапки и есть
    категории сайта (export/groups + export/products);
  - состав — export/tech-cards на сегодня, раскрываем до сырья тем же
    алгоритмом, что и техкарты iiko (iiko_sync._composition_from_tree);
  - себестоимость — export/dish-costs, поле ССС (ssc).

Фото в O·ERP нет: уже скачанные остаются, новые грузят в админке. Блюда,
пропавшие из папок, не удаляем — только пишем в лог, как и синхронизация iiko.

Пока не сверено с прошлой загрузкой из iiko, основной остаётся iiko:
источник выбирает настройка PRODUCT_SOURCE, сверка — команда
`manage.py oerp_sync --compare`.
"""

import logging
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.utils import timezone as dj_timezone

from .iiko_sync import (
    _build_label_to_key,
    _composition_from_tree,
    _fields_changed,
    _parse_description,
    _per_serving,
    _request_with_retry,
)

logger = logging.getLogger(__name__)

OERP_DEFAULT_URL = "https://new.erp-system-fz.kz/api/v1/export"
ROOT_FOLDER = "ЗДОРОВОЕ ПИТАНИЕ"

# Наибольшие страницы, которые принимает O·ERP (export.dto.ts / use-cases)
PAGE_PRODUCTS = 1000
PAGE_GROUPS = 1000
PAGE_TECH_CARDS = 500
PAGE_DISH_COSTS = 1000

# Поля, которые сверяет `oerp_sync --compare` (раздел 7 документа O·ERP)
COMPARE_FIELDS = [
    "name", "article", "net_weight",
    "kcal_per_100", "protein", "fat", "carbs",
    "kcal_per_serving", "protein_per_serving", "fat_per_serving", "carbs_per_serving",
    "composition", "cost",
]


# ──────────────────────────────────────────────────────────────────────────────
# Клиент
# ──────────────────────────────────────────────────────────────────────────────

class OerpError(Exception):
    pass


class OerpClient:
    """Чтение export-API O·ERP по ключу (Bearer erpk_…). Входа и выхода нет."""

    def __init__(self, api_key: str, base_url: str = OERP_DEFAULT_URL):
        self.api_key = api_key
        self.base = (base_url or OERP_DEFAULT_URL).rstrip("/")

    def _get(self, resource: str, params: dict) -> dict:
        resp = _request_with_retry(
            "get", f"{self.base}/{resource}",
            params=params,
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
            timeout=120,
        )
        if resp.status_code >= 400:
            raise OerpError(f"{resource}: HTTP {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        if data.get("result") != "SUCCESS":
            raise OerpError(f"{resource}: {data.get('errors') or data}")
        return data

    def fetch_all(self, resource: str, page_size: int, **params) -> list:
        """Все страницы ресурса: limit/offset, пока paging.hasMore."""
        rows, offset = [], 0
        while True:
            data = self._get(resource, {**params, "limit": page_size, "offset": offset})
            page = data.get("response") or []
            rows.extend(page)
            if not (data.get("paging") or {}).get("hasMore") or not page:
                return rows
            offset += len(page)


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────

def _num(val):
    """Число O·ERP приходит текстом ("0.320"); «не посчитано» — null."""
    if val is None or val == "":
        return None
    try:
        return float(Decimal(str(val)))
    except (InvalidOperation, ValueError):
        return None


def _folder_display(name: str) -> str:
    """«1ПП* ЗАВТРАК» → «ПП* ЗАВТРАК»: в O·ERP у папок цифра порядка спереди."""
    return re.sub(r"^\d+\s*", "", (name or "").strip())


def _folder_key(label: str) -> str:
    """Ключ сравнения имени папки с картой категорий: без ведущих цифр,
    регистра, вида тире, слова «ккал» и пробелов — «ПП* ДОП.ТОВАРЫ» в O·ERP
    и «ПП* Доп. товары» во внешнем меню iiko должны совпасть."""
    s = _folder_display(label).lower()
    s = re.sub(r"[‐-―−]", "-", s)
    s = s.replace("ккал", "")
    return re.sub(r"\s+", "", s)


def _category_map() -> dict:
    """{ключ папки: slot_key} из той же карты категорий, что у iiko
    (встроенные названия + IikoCategoryMap из админки)."""
    return {_folder_key(label): key for label, key in _build_label_to_key().items()}


def _dish_folders(groups: list, label_to_key: dict) -> dict:
    """Папки внутри «ЗДОРОВОЕ ПИТАНИЕ», которые попадают в категорию сайта:
    {group_id: (имя для отображения, slot_key)}.

    Категория — у ближайшей папки с известным именем (своей или родителя),
    поэтому вложенные подпапки наследуют категорию. Папки без категории
    (ФМД, MAGNUM CHEF) не берём. Пары одноимённых папок (одна пустая) не
    мешают: сравниваем по имени, id не важен."""
    alive = [g for g in groups if not g.get("deleted")]
    children = {}
    for g in alive:
        children.setdefault(g.get("parentId"), []).append(g)

    roots = [g for g in alive if (g.get("name") or "").strip().upper() == ROOT_FOLDER]
    result = {}

    def walk(folder, inherited):
        own = label_to_key.get(_folder_key(folder.get("name")))
        current = (_folder_display(folder.get("name")), own) if own else inherited
        if current:
            result[folder["id"]] = current
        for child in children.get(folder["id"], []):
            walk(child, current)

    for root in roots:
        for child in children.get(root["id"], []):
            walk(child, None)
    return result


def _cards_as_iiko_charts(cards: list) -> tuple:
    """export/tech-cards → вход iiko_sync._composition_from_tree:
    ([{assembledProductId, dateFrom, dateTo, items:[{productId, amount*}]}],
     {productId: {"name": ...}}).

    Количества переводим из текста в числа: строка "0.000" истинна, и
    алгоритм не перешёл бы с нулевого выхода на нетто, как с числами iiko."""
    charts, names = [], {}
    for card in cards:
        items = []
        for it in card.get("items") or []:
            pid = it.get("productId")
            if not pid:
                continue
            names.setdefault(pid, {"name": it.get("name") or ""})
            items.append({
                "productId": pid,
                "amountOut": _num(it.get("amountOut")),
                "amountMiddle": _num(it.get("amountMiddle")),
                "amountIn": _num(it.get("amountIn")),
            })
        charts.append({
            "assembledProductId": card.get("productId"),
            "dateFrom": card.get("dateFrom"),
            "dateTo": card.get("dateTo"),
            "items": items,
        })
    return charts, names


# ──────────────────────────────────────────────────────────────────────────────
# Сбор данных
# ──────────────────────────────────────────────────────────────────────────────

def collect_from_oerp(client: OerpClient, on_date: str = None) -> dict:
    """Скачивает всё нужное и собирает блюда Olive. В базу ничего не пишет.

    Возвращает {"items": {id: поля}, "stats": {...}, "errors": [...]}, где
    поля — уже в виде полей Product плюс служебные "_slot_key" и "_code"."""
    on_date = on_date or date.today().strftime("%Y-%m-%d")
    errors = []

    groups = client.fetch_all("groups", PAGE_GROUPS)
    folders = _dish_folders(groups, _category_map())
    if not folders:
        raise OerpError(f"В O·ERP не найдена папка «{ROOT_FOLDER}» с известными подпапками")

    rows = []
    for kind in ("dish", "goods"):          # «ПП* ДОП.ТОВАРЫ» — товары, не блюда
        rows += [r for r in client.fetch_all("products", PAGE_PRODUCTS, kind=kind)
                 if r.get("groupId") in folders and not r.get("deleted")]

    # Себестоимость: блюда/заготовки и отдельно товары
    cost_by_id, cost_by_code = {}, {}
    try:
        costs = client.fetch_all("dish-costs", PAGE_DISH_COSTS, date=on_date)
        costs += client.fetch_all("dish-costs", PAGE_DISH_COSTS, date=on_date, kind="goods")
        for c in costs:
            # ССС; в документе O·ERP поле названо sss, в коде API — ssc
            val = _num(c.get("ssc", c.get("sss")))
            if val is None:
                continue
            if c.get("id"):
                cost_by_id[c["id"]] = val
            if c.get("code"):
                cost_by_code[str(c["code"]).strip()] = val
    except Exception as e:
        logger.warning(f"O·ERP dish-costs: {e}")
        errors.append(f"Себестоимость: {e}")

    # Техкарты всех блюд и заготовок на дату — одним списком
    charts, chart_names = [], {}
    try:
        charts, chart_names = _cards_as_iiko_charts(
            client.fetch_all("tech-cards", PAGE_TECH_CARDS, date=on_date))
    except Exception as e:
        logger.warning(f"O·ERP tech-cards: {e}")
        errors.append(f"Техкарты: {e}")
    has_card = {c["assembledProductId"] for c in charts}

    items = {}
    stats = {"products": len(rows), "with_card": 0, "from_description": 0,
             "with_cost": 0, "no_cost": []}
    for r in rows:
        pid = r["id"]
        code = str(r.get("code") or "").strip()
        display, slot_key = folders[r["groupId"]]
        fields = {
            "name": (r.get("name") or "").strip(),
            "article": code,
            "iiko_category": display,
            "iiko_id": pid,
            "_slot_key": slot_key,
            "_code": code,
        }
        if r.get("baseUomName"):
            fields["packing"] = r["baseUomName"]

        weight_g = None
        uw = _num(r.get("unitWeightKg"))
        if uw and uw > 0:
            weight_g = float(Decimal(str(uw)) * 1000)
            grams = Decimal(str(weight_g)).quantize(Decimal("1"), ROUND_HALF_UP)
            fields["net_weight"] = float(grams) / 1000

        per100 = ((r.get("nutrition") or {}).get("per100g")) or {}
        kcal = _num(per100.get("kcal"))
        values = {
            "kcal_per_100": kcal,
            "protein": _num(per100.get("protein")),
            "fat": _num(per100.get("fat")),
            "carbs": _num(per100.get("carbs")),
            "kj_per_100": round(kcal * 4.184, 2) if kcal is not None else None,
        }
        for src, dst in (("kcal_per_100", "kcal_per_serving"), ("protein", "protein_per_serving"),
                         ("fat", "fat_per_serving"), ("carbs", "carbs_per_serving"),
                         ("kj_per_100", "kj_per_serving")):
            values[dst] = _per_serving(values[src], weight_g)
        fields.update({k: v for k, v in values.items() if v is not None})

        comp = ""
        if pid in has_card:
            comp = _composition_from_tree(pid, charts, chart_names)
            if comp:
                stats["with_card"] += 1
        if not comp:
            comp = _parse_description(r.get("description"))
            if comp:
                stats["from_description"] += 1
        if comp:
            fields["composition"] = comp

        cost = cost_by_id.get(pid)
        if cost is None and code:
            cost = cost_by_code.get(code)
        if cost is not None:
            # «не посчитано» (null) не пишем вовсе — старое значение остаётся
            fields["cost"] = Decimal(str(round(cost, 2)))
            stats["with_cost"] += 1
        else:
            stats["no_cost"].append(fields["name"])

        items[pid] = fields

    logger.info(
        f"O·ERP: блюд {len(items)}, состав из техкарт {stats['with_card']}, "
        f"из описания {stats['from_description']}, себестоимость {stats['with_cost']}"
    )
    return {"items": items, "stats": stats, "errors": errors}


# ──────────────────────────────────────────────────────────────────────────────
# Запись в базу / сверка
# ──────────────────────────────────────────────────────────────────────────────

def _match_existing(items: dict) -> dict:
    """{id из O·ERP: Product} — как у iiko: сначала по артикулу (если он
    уникален и в выгрузке, и в базе), затем по iiko_id, затем по iiko_sku."""
    from collections import Counter
    from .models import Product

    feed_codes = Counter(f["_code"] for f in items.values() if f["_code"])
    unique_codes = {c for c, n in feed_codes.items() if n == 1}
    by_article, dup = {}, set()
    for p in Product.objects.filter(article__in=unique_codes):
        a = (p.article or "").strip()
        if a in by_article:
            dup.add(a)
        else:
            by_article[a] = p
    for a in dup:
        by_article.pop(a, None)

    ids = set(items)
    by_iiko_id = {p.iiko_id: p for p in Product.objects.filter(iiko_id__in=ids)}
    by_sku = {p.iiko_sku: p for p in Product.objects.filter(iiko_sku__in=ids)}

    matched = {}
    for pid, f in items.items():
        p = by_article.get(f["_code"]) or by_iiko_id.get(pid) or by_sku.get(pid)
        if p is not None:
            matched[pid] = p
    return matched


def _same(old, new) -> bool:
    if old is None and new is None:
        return True
    try:
        return round(float(old), 2) == round(float(new), 2)
    except (TypeError, ValueError):
        return str(old or "") == str(new or "")


def compare_with_db(collected: dict) -> dict:
    """Сверка выгрузки O·ERP с тем, что сейчас в базе (загружено из iiko).
    Ничего не пишет. Числа — с округлением до 2 знаков."""
    from .models import Product

    items = collected["items"]
    matched = _match_existing(items)
    diffs = {f: [] for f in COMPARE_FIELDS}
    for pid, p in matched.items():
        new = items[pid]
        for f in COMPARE_FIELDS:
            if f not in new:
                continue                    # нет в O·ERP — при загрузке не тронем
            if not _same(getattr(p, f), new[f]):
                diffs[f].append((p.pk, p.name, getattr(p, f), new[f]))

    matched_pks = {p.pk for p in matched.values()}
    return {
        "feed": len(items),
        "matched": len(matched),
        "new": [items[pid]["name"] for pid in items if pid not in matched],
        "missing": list(Product.objects.exclude(pk__in=matched_pks)
                        .order_by("name").values_list("name", flat=True)),
        "diffs": diffs,
        "same_id": sum(1 for pid, p in matched.items() if p.iiko_id == pid),
    }


def sync_products_from_oerp(api_key: str, base_url: str = OERP_DEFAULT_URL) -> dict:
    """Загрузка из O·ERP в базу. Ответ — в том же виде, что у
    iiko_sync.sync_products_from_iiko (его показывает кнопка в каталоге)."""
    from .models import MealCategory, Product

    result = {"created": 0, "updated": 0, "skipped": 0,
              "deleted": 0, "unchanged": 0, "errors": []}
    try:
        collected = collect_from_oerp(OerpClient(api_key, base_url))
    except Exception as e:
        result["errors"].append(f"O·ERP: {e}")
        return result
    result["errors"] += collected["errors"]

    items = collected["items"]
    matched = _match_existing(items)
    categories = {c.key: c for c in MealCategory.objects.all()}
    now = dj_timezone.now()

    for pid, fields in items.items():
        try:
            slot_key = fields["_slot_key"]
            new_fields = {k: v for k, v in fields.items() if not k.startswith("_")}
            product = matched.get(pid)
            if product is None:
                product = Product.objects.create(**new_fields, iiko_sku=pid, iiko_synced_at=now)
                result["created"] += 1
            else:
                changed, changed_fields = _fields_changed(product, new_fields)
                if changed:
                    for k, v in new_fields.items():
                        setattr(product, k, v)
                    product.iiko_synced_at = now
                    product.save()
                    result["updated"] += 1
                    logger.debug(f"Обновлён '{product.name}': {changed_fields}")
                else:
                    result["unchanged"] += 1

            cat = categories.get(slot_key)
            if cat and set(product.meal_categories.values_list("pk", flat=True)) != {cat.pk}:
                product.meal_categories.set([cat])
        except Exception as e:
            msg = f"'{fields.get('name', pid)}': {e}"
            logger.error(f"O·ERP: {msg}")
            result["errors"].append(msg)
            result["skipped"] += 1

    # Не удаляем — только кандидаты в лог, как у iiko (защита рационов)
    matched_pks = {p.pk for p in _match_existing(items).values()}
    gone = list(Product.objects.exclude(pk__in=matched_pks).values_list("name", flat=True))
    if gone:
        logger.warning(f"Нет в папках O·ERP (НЕ удалены): {len(gone)}: {gone}")
        result["delete_candidates"] = len(gone)

    logger.info(
        f"O·ERP готово — создано: {result['created']}, обновлено: {result['updated']}, "
        f"без изменений: {result['unchanged']}, пропущено: {result['skipped']}"
    )
    return result
