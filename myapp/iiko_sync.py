"""
iiko_sync.py — умная синхронизация продуктов из iiko в O-Live.

Ключ синхронизации: артикул (num) из iiko — поле iiko_sku в Product.

Логика обновления:
  - Новые блюда (нет в БД) → создаём + скачиваем фото
  - Существующие блюда → сравниваем поля, обновляем ТОЛЬКО если что-то изменилось
  - Фото → скачиваем только если URL изменился или фото нет
  - Аллергены → берём из item.allergens, get_or_create по имени
  - Удалённые из iiko → удаляем из БД

Состав блюда — из технологической карты iiko Server
(/api/v2/assemblyCharts/getPrepared): iiko сам раскрывает дерево ТК до конечного
сырья. Из списка убираем упаковку (У*) и «Смесь газ», срезаем префиксы (С*, П*
и т.п.), убираем дубли. Если prepared-карты нет — фолбэк на description продукта.
"""

import re
from decimal import Decimal
import time
import hashlib
import requests
import logging
import json as _json
import os
from concurrent.futures import ThreadPoolExecutor
from django.utils import timezone as dj_timezone
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# ── Защита от блокировки ──────────────────────────────────────────────────────
RATE_LIMIT_DELAY  = 0.2
MAX_RETRIES       = 3
RETRY_DELAY       = 5
MIN_SYNC_INTERVAL = 5  # временно уменьшено для тестирования категорий
COMPOSITION_WORKERS = 8  # параллельных запросов техкарт к iiko Server

_last_sync_time = 0

# ── Точное совпадение название группы iiko → ключ SLOT_TYPES ─────────────────
_SLOT_LABEL_TO_KEY = {
    # Старые (дробные) названия из iiko → новые объединённые категории сайта
    'Завтрак 250–350 ккал':        'breakfast',
    'Завтрак 400–500 ккал':        'breakfast',
    'Второе 400–500 ккал':         'hot_400',
    'Второе 500–600 ккал':         'hot_500',
    'Суп 200 ккал':                'soup',
    'Суп 300 ккал':                'soup',
    'Салат 150–250 ккал':          'salad',
    'Салат 250–350 ккал':          'salad',
    'Выпечка/Десерт 100–250 ккал': 'dessert',
    'Выпечка/Десерт 300–350 ккал': 'dessert',
    'Смузи 100–150 ккал':          'smoothie',
    'Сэндвич 300–350 ккал':        'sandwich',
    # Новые названия (на случай если в iiko переименуют как на сайте)
    'Завтрак':          'breakfast',
    'Горячее 400-500':  'hot_400',
    'Горячее 500-600':  'hot_500',
    'Суп':              'soup',
    'Салат':            'salad',
    'Выпечка/Десерт':   'dessert',
    'Смузи':            'smoothie',
    'Сэндвичи':         'sandwich',
}


def _normalize_label(s: str) -> str:
    """Приводит название группы к единому виду для сравнения:
    разные виды тире/дефиса → '-', убираем слово 'ккал', лишние пробелы, регистр."""
    s = s.strip().lower()
    s = re.sub(r'[‐-―−]', '-', s)
    s = re.sub(r'\s*ккал\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


_SLOT_LABEL_TO_KEY_NORM = {
    _normalize_label(label): key for label, key in _SLOT_LABEL_TO_KEY.items()
}


def _build_label_to_key() -> dict:
    """Нормализованное сопоставление {название_категории_iiko: slot_key}.
    Берёт встроенные значения из кода + редактируемые из админки (БД),
    записи из БД имеют приоритет."""
    result = dict(_SLOT_LABEL_TO_KEY_NORM)  # встроенные дефолты
    try:
        from .models import IikoCategoryMap
        for row in IikoCategoryMap.objects.all():
            result[_normalize_label(row.iiko_name)] = row.slot_key
    except Exception as e:
        logger.warning(f"Не удалось загрузить сопоставление категорий из БД: {e}")
    return result


def _pick_category(menu_info: dict, label_to_key: dict = None) -> tuple:
    """Блюдо может входить сразу в несколько категорий внешнего меню
    (например, ещё в техническую категорию типа 'ПП Упак').
    Возвращает (название_категории_для_отображения, slot_key_или_None) —
    выбираем первую категорию, совпавшую с категорией сайта, иначе первую попавшуюся."""
    if label_to_key is None:
        label_to_key = _SLOT_LABEL_TO_KEY_NORM
    cat_names = menu_info.get("category_names") or []
    if not cat_names and menu_info.get("category_name"):
        cat_names = [menu_info["category_name"]]

    for cn in cat_names:
        cn = (cn or "").strip()
        if not cn:
            continue
        slot_key = label_to_key.get(_normalize_label(cn))
        if slot_key:
            return cn, slot_key

    first = next((cn.strip() for cn in cat_names if cn and cn.strip()), "")
    return first, None

_COMPARE_FIELDS = [
    "name", "article", "iiko_category", "packing", "net_weight",
    "kcal_per_100", "protein", "fat", "carbs", "kj_per_100",
    "kcal_per_serving", "protein_per_serving", "fat_per_serving",
    "carbs_per_serving", "kj_per_serving", "composition", "cost",
]


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _round_for_compare(val):
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return val


def _fields_changed(product, new_fields: dict) -> tuple:
    changed = []
    for field in _COMPARE_FIELDS:
        if field not in new_fields:
            continue
        old_val = getattr(product, field, None)
        new_val = new_fields[field]
        if isinstance(new_val, float) or isinstance(old_val, float):
            if _round_for_compare(old_val) != _round_for_compare(new_val):
                changed.append(field)
        else:
            old_str = str(old_val) if old_val is not None else ""
            new_str = str(new_val) if new_val is not None else ""
            if old_str != new_str:
                changed.append(field)
    return bool(changed), changed


def _request_with_retry(method, url, **kwargs):
    resp = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = getattr(requests, method)(url, **kwargs)
            if resp.status_code in (429, 503):
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"HTTP {resp.status_code} — ждём {wait}с (попытка {attempt+1})")
                time.sleep(wait)
                continue
            return resp
        except requests.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            raise
    return resp


def _parse_description(desc) -> str:
    if not desc:
        return ""
    if isinstance(desc, str):
        try:
            desc = _json.loads(desc)
        except Exception:
            return desc.strip()
    if isinstance(desc, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in desc
        ).strip()
    if isinstance(desc, dict):
        return desc.get("text", str(desc)).strip()
    return str(desc).strip()


# ── Состав из технологической карты ──────────────────────────────────────────

# Префикс вида "С* ", "П* ", "Б* ", "ПП* " в начале названия продукта iiko
_INGR_PREFIX_RE = re.compile(r'^[А-ЯЁA-Z]{1,3}\*\s*')


def _ingredient_excluded(name: str) -> bool:
    """Упаковка (У*) и техпозиции типа «Смесь газ» — не еда, в состав не идут."""
    n = (name or '').strip()
    if n.startswith('У*'):
        return True
    if 'смесь газ' in n.lower():
        return True
    return False


def _clean_ingredient(name: str) -> str:
    """Срезает префикс 'С* '/'П* '/... и лишние пробелы."""
    return _INGR_PREFIX_RE.sub('', (name or '').strip()).strip()


def _tree_leaves(root_pid: str, charts: list) -> list:
    """Рекурсивно обходит дерево ТК (getTree) от корневого блюда и возвращает
    список листьев [(productId, effective_amount)] — конечное сырьё.

    Лист = продукт, у которого в дереве нет своего узла-сборки. Так мы обходим
    ограничение getPrepared: если полуфабрикат-основа (Б*/П*) списывается
    напрямую (DIRECT), getPrepared в него не заходит и теряет ингредиенты,
    а в дереве узел есть — и мы раскрываем его сами.
    """
    # На один продукт может быть несколько карт (разные периоды действия) —
    # берём актуальную: сначала действующую (dateTo=None), затем с поздней dateFrom.
    node_by_product = {}
    for c in charts or []:
        apid = c.get("assembledProductId")
        if not apid:
            continue
        cur = node_by_product.get(apid)
        if cur is None:
            node_by_product[apid] = c
        elif (c.get("dateTo") is None and cur.get("dateTo") is not None) or \
             (str(c.get("dateFrom") or "") > str(cur.get("dateFrom") or "")):
            node_by_product[apid] = c

    leaves = []
    visited = set()

    def walk(pid, amount):
        if pid in visited:
            return
        visited.add(pid)
        node = node_by_product.get(pid)
        if not node:  # нет своей сборки → лист (конечное сырьё)
            leaves.append((pid, amount))
            return
        for it in node.get("items") or []:
            sub = it.get("productId")
            if not sub:
                continue
            try:
                a = float(it.get("amountOut") or it.get("amountMiddle")
                          or it.get("amountIn") or 0)
            except (TypeError, ValueError):
                a = 0.0
            walk(sub, (amount * a) if amount else a)

    walk(root_pid, 1.0)
    return leaves


def _composition_from_tree(root_pid: str, charts: list, products_by_id: dict) -> str:
    """Строка состава из дерева ТК: раскрываем до сырья, убираем упаковку (У*)
    и «Смесь газ», срезаем префиксы (С*/П*/Б*/...), суммируем количества
    одинакового сырья и сортируем по убыванию (основной ингредиент первым),
    дубли по нормализованному имени схлопываем.
    """
    agg = {}  # normalized_name -> [display_name, total_amount]
    for pid, amount in _tree_leaves(root_pid, charts):
        p = products_by_id.get(pid)
        if not p:
            continue
        nm = p.get("name") or ""
        if _ingredient_excluded(nm):
            continue
        cn = _clean_ingredient(nm)
        if not cn:
            continue
        k = re.sub(r'\s+', ' ', cn).lower()
        if k not in agg:
            agg[k] = [cn, 0.0]
        agg[k][1] += (amount or 0.0)

    ordered = sorted(agg.values(), key=lambda x: -x[1])
    return ", ".join(name for name, _amt in ordered)


def _download_photo(url: str) -> tuple:
    if not url or not url.startswith("http"):
        return None, None
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return None, None
        content_type = resp.headers.get("Content-Type", "")
        if "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        elif "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        else:
            url_path = url.split("?")[0]
            ext = os.path.splitext(url_path)[1] or ".jpg"
        return resp.content, ext
    except Exception as e:
        logger.warning(f"Не удалось скачать фото {url}: {e}")
        return None, None


def _photo_url_changed(product, new_url: str) -> bool:
    if not product.photo:
        return True
    if not new_url:
        return False
    url_hash = hashlib.md5(new_url.encode()).hexdigest()[:8]
    current_name = os.path.basename(str(product.photo.name))
    return url_hash not in current_name


# ──────────────────────────────────────────────────────────────────────────────
# iikoCloud клиент
# ──────────────────────────────────────────────────────────────────────────────

class IikoCloudClient:
    BASE = "https://api-ru.iiko.services"

    def __init__(self, api_key: str, app_id: str = "", client_secret: str = ""):
        self.api_key = api_key
        self.app_id = app_id
        self.client_secret = client_secret
        self._token = None

    def _get_token(self) -> str:
        # Новая схема авторизации (iikoTransport): если задано зарегистрированное
        # приложение (appId + clientSecret) — используем эндпоинт /api/v2/access_token.
        # Старый /api/1/access_token отключается iiko (~29.08.2026), оставлен только
        # как запасной вариант, если приложение ещё не настроено.
        if self.app_id and self.client_secret:
            resp = _request_with_retry(
                "post", f"{self.BASE}/api/v2/access_token",
                json={
                    "apiLogin": self.api_key,
                    "appId": self.app_id,
                    "clientSecret": self.client_secret,
                }, timeout=20,
            )
        else:
            resp = _request_with_retry(
                "post", f"{self.BASE}/api/1/access_token",
                json={"apiLogin": self.api_key}, timeout=20,
            )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        return self._token

    def _headers(self) -> dict:
        if not self._token:
            self._get_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def get_nomenclature(self, org_id: str) -> dict:
        resp = _request_with_retry(
            "post", f"{self.BASE}/api/1/nomenclature",
            json={"organizationId": org_id, "startRevision": 0},
            headers=self._headers(), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_menu_by_id(self, menu_id: str, org_id: str) -> dict:
        resp = _request_with_retry(
            "post", f"{self.BASE}/api/2/menu/by_id",
            json={
                "externalMenuId": menu_id,
                "organizationIds": [org_id],
                "priceCategoryId": "00000000-0000-0000-0000-000000000000",
                "version": 2,
            },
            headers=self._headers(), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# iiko Server клиент
# ──────────────────────────────────────────────────────────────────────────────

class IikoServerClient:
    def __init__(self, server_url: str, login: str, password: str):
        self.base = server_url.rstrip("/")
        self.login = login
        self.password = password
        self._token = None

    def _get_token(self) -> str:
        resp = _request_with_retry(
            "get", f"{self.base}/api/auth",
            params={"login": self.login, "pass": self.password}, timeout=20,
        )
        resp.raise_for_status()
        self._token = resp.text.strip().strip('"')
        return self._token

    def _params(self, extra: dict = None) -> dict:
        if not self._token:
            self._get_token()
        p = {"key": self._token}
        if extra:
            p.update(extra)
        return p

    def logout(self):
        if self._token:
            try:
                requests.get(
                    f"{self.base}/api/auth/logout",
                    params={"key": self._token}, timeout=10,
                )
            except Exception:
                pass
            finally:
                self._token = None

    def get_products(self) -> list:
        resp = _request_with_retry(
            "get", f"{self.base}/api/v2/entities/products/list",
            params=self._params({"includeDeleted": "false"}), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_assembly_tree(self, product_id: str) -> list:
        """Полное дерево техкарт блюда (getTree) — список узлов assemblyCharts.
        В отличие от getPrepared, содержит и полуфабрикаты со списанием DIRECT,
        поэтому состав раскрывается до сырья без потерь. Пусто = карты нет."""
        from datetime import date
        resp = _request_with_retry(
            "get", f"{self.base}/api/v2/assemblyCharts/getTree",
            params=self._params({
                "date": date.today().strftime("%Y-%m-%d"),
                "productId": product_id,
            }), timeout=60,
        )
        resp.raise_for_status()
        if not resp.text.strip():
            return []
        return resp.json().get("assemblyCharts") or []

    def get_cost_report(self) -> dict:
        """OLAP-отчёт себестоимости за текущий месяц.
        Контрагент: 0Частное лицо Покупатель, тип транзакции: OUTGOING_INVOICE.
        Возвращает сырой JSON ответа iiko Server.
        """
        from datetime import date
        today = date.today()
        first_day = today.replace(day=1)
        if today.month == 12:
            next_first = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_first = today.replace(month=today.month + 1, day=1)

        body = {
            "reportType": "TRANSACTIONS",
            "groupByRowFields": ["Product.Name"],
            "groupByColFields": [],
            # Amount.Out — количество в строке накладной; цена за единицу
            # считается как Sum.Incoming / Amount.Out (см. _parse_cost_report)
            "aggregateFields": ["Sum.Incoming", "Amount.Out"],
            "filters": {
                "DateTime.OperDayFilter": {
                    "filterType": "DateRange",
                    "from": first_day.strftime("%Y-%m-%dT00:00:00"),
                    "to": next_first.strftime("%Y-%m-%dT00:00:00"),
                    "includeLow": True,
                    "includeHigh": False,
                    "periodType": "CURRENT_MONTH",
                },
                "Product.ThirdParent": {
                    "filterType": "IncludeValues",
                    "values": ["ЗДОРОВОЕ ПИТАНИЕ"],
                },
                "TransactionType": {
                    "filterType": "IncludeValues",
                    "values": ["OUTGOING_INVOICE"],
                },
                "Counteragent.Name": {
                    "filterType": "IncludeValues",
                    "values": ["0Частное лицо Покупатель"],
                },
            },
        }

        resp = _request_with_retry(
            "post", f"{self.base}/api/v2/reports/olap",
            json=body,
            params=self._params(),
            headers={"Accept": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# Парсер внешнего меню
# ──────────────────────────────────────────────────────────────────────────────

def _extract_menu_items(menu_data: dict) -> dict:
    """
    Возвращает {product_uuid: {name, category_name, packing, weight,
                               photo_url, allergen_names, КБЖУ...}}
    allergen_names — список строк с именами аллергенов
    """
    result = {}

    def _parse_item(item: dict, cat_name: str):
        product_id = item.get("itemId") or item.get("id") or ""
        name = item.get("name") or ""
        if not product_id or not name:
            return

        # Блюдо может входить в несколько категорий внешнего меню —
        # копим все варианты, чтобы потом выбрать подходящую под SLOT_TYPES.
        if product_id in result:
            existing_cats = result[product_id]["category_names"]
            if cat_name and cat_name not in existing_cats:
                existing_cats.append(cat_name)
            return

        sizes = item.get("itemSizes") or []
        size = sizes[0] if sizes else {}

        nutr = size.get("nutritionPerHundredGrams") or {}
        if isinstance(nutr, list):
            nutr = nutr[0] if nutr else {}
        if not nutr:
            nutritions = size.get("nutritions") or []
            nutr = nutritions[0] if nutritions else {}

        weight_grams = _safe_float(size.get("portionWeightGrams"))

        kcal_100    = _safe_float(nutr.get("energy"))
        protein_100 = _safe_float(nutr.get("proteins"))
        fat_100     = _safe_float(nutr.get("fats"))
        carbs_100   = _safe_float(nutr.get("carbs"))
        kj_100      = round(kcal_100 * 4.184, 2) if kcal_100 is not None else None

        def per_serving(val):
            if val is not None and weight_grams:
                return round(val * weight_grams / 100, 2)
            return None

        photo_url = (
            size.get("buttonImageUrl")
            or item.get("buttonImageUrl")
            or ""
        )

        # Артикул блюда из внешнего меню iiko (короткий код)
        article = (
            item.get("sku")
            or size.get("sku")
            or item.get("code")
            or size.get("code")
            or ""
        )
        article = str(article).strip()

        # Аллергены — берём из item.allergens
        # Формат: [{id, code, name, isDeleted}, ...]
        allergen_names = []
        for a in item.get("allergens") or []:
            a_name = a.get("name") or ""
            a_deleted = str(a.get("isDeleted", "false")).lower()
            if a_name and a_deleted != "true":
                allergen_names.append(a_name.strip())

        result[product_id] = {
            "name":           name,
            "category_name":  cat_name,
            "category_names": [cat_name] if cat_name else [],
            "article":        article,
            "packing":        item.get("measureUnit") or "",
            "weight":         weight_grams,
            "photo_url":      photo_url,
            "allergen_names": allergen_names,  # список имён аллергенов
            "kcal":           kcal_100,
            "protein":        protein_100,
            "fat":            fat_100,
            "carbs":          carbs_100,
            "kj_100":         kj_100,
            "kcal_s":         per_serving(kcal_100),
            "protein_s":      per_serving(protein_100),
            "fat_s":          per_serving(fat_100),
            "carbs_s":        per_serving(carbs_100),
            "kj_s":           per_serving(kj_100),
        }

    def walk_categories(categories: list, parent_name: str = ""):
        for cat in categories or []:
            cat_name = cat.get("name") or parent_name or ""
            walk_categories(cat.get("childCategories") or [], cat_name)
            for item in cat.get("items") or []:
                _parse_item(item, cat_name)

    walk_categories(menu_data.get("itemCategories") or [])
    if not result:
        for pcat in menu_data.get("productCategories") or []:
            cat_name = pcat.get("name") or ""
            for item in pcat.get("items") or []:
                _parse_item(item, cat_name)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Парсер OLAP-отчёта себестоимости
# ──────────────────────────────────────────────────────────────────────────────

def _norm_name(s) -> str:
    """Нормализует название блюда: схлопывает пробелы, нижний регистр."""
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower()


def _norm_name_nosuffix(s) -> str:
    """То же + убирает хвостовой суффикс в скобках, напр. '(1порц)', '(3шт)'."""
    s = _norm_name(s)
    return re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()


def _parse_cost_report(report_data: dict) -> dict:
    """Возвращает {product_name: себестоимость за единицу} из OLAP-отчёта.

    В отчёте Sum.Incoming — сумма по строке накладной, Amount.Out — количество
    в ней. Себестоимость единицы = сумма / количество: без деления позиция,
    ушедшая не по одной штуке, получала кратно завышенную цену.
    Строки с нулевым количеством пропускаем — цену из них не вывести.
    """
    costs = {}
    columns = report_data.get("columnNames") or report_data.get("columns") or []
    rows = report_data.get("data") or []

    if not rows:
        return costs

    def put(name, total, amount):
        name = str(name or "").strip()
        if not name:
            return
        try:
            total = float(total)
            amount = float(amount if amount is not None else 0)
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return
        costs[name] = total / amount

    # Формат 1: список имён колонок + список строк-списков
    if columns:
        def index_of(key):
            return next((i for i, c in enumerate(columns) if key in str(c)), None)

        name_idx = index_of("Product.Name")
        cost_idx = index_of("Sum.Incoming")
        amount_idx = index_of("Amount.Out")
        if name_idx is not None and cost_idx is not None:
            needed = max(i for i in (name_idx, cost_idx, amount_idx) if i is not None)
            for row in rows:
                if not isinstance(row, list) or len(row) <= needed:
                    continue
                amount = row[amount_idx] if amount_idx is not None else 1
                put(row[name_idx], row[cost_idx], amount)
        return costs

    # Формат 2: строки-словари
    if isinstance(rows[0], dict):
        for row in rows:
            put(row.get("Product.Name"), row.get("Sum.Incoming") or 0,
                row.get("Amount.Out", 1))

    return costs
# ──────────────────────────────────────────────────────────────────────────────
# Главная функция синхронизации
# ──────────────────────────────────────────────────────────────────────────────

def sync_products_from_iiko(
    cloud_api_key: str,
    org_id: str,
    external_menu_id: str,
    server_url: str = "",
    server_login: str = "",
    server_password: str = "",
    cloud_app_id: str = "",
    cloud_client_secret: str = "",
) -> dict:
    global _last_sync_time

    now_ts = time.time()
    elapsed = now_ts - _last_sync_time
    if elapsed < MIN_SYNC_INTERVAL:
        wait_left = int(MIN_SYNC_INTERVAL - elapsed)
        return {
            "created": 0, "updated": 0, "skipped": 0, "deleted": 0,
            "errors": [f"Синхронизация запущена слишком часто. Подождите ещё {wait_left} сек."]
        }

    from .models import Product, MealCategory, Allergen

    result = {
        "created": 0, "updated": 0, "skipped": 0,
        "deleted": 0, "unchanged": 0, "errors": []
    }

    cloud = IikoCloudClient(cloud_api_key, cloud_app_id, cloud_client_secret)

    # ── Шаг 1: Внешнее меню ──────────────────────────────────────────────────
    try:
        menu_data = cloud.get_menu_by_id(external_menu_id, org_id)
    except Exception as e:
        result["errors"].append(f"iikoCloud menu: {e}")
        return result

    menu_map = _extract_menu_items(menu_data)
    if not menu_map:
        result["errors"].append("iikoCloud: блюд в меню не найдено.")
        return result

    logger.info(f"iikoCloud menu: {len(menu_map)} блюд")

    # Диагностика: какие категории реально приходят из iiko и совпадают ли с SLOT_TYPES
    all_cat_names = {}
    for info in menu_map.values():
        for cn in info.get("category_names") or []:
            if cn:
                all_cat_names[cn] = all_cat_names.get(cn, 0) + 1
    for cn, cnt in sorted(all_cat_names.items()):
        matched = _SLOT_LABEL_TO_KEY_NORM.get(_normalize_label(cn))
        codes = " ".join(f"U+{ord(c):04X}" for c in cn if not c.isalnum() and not c.isspace())
        logger.info(
            f"iiko категория: '{cn}' (символы: {codes or '-'}) — блюд: {cnt} "
            f"— match: {matched or 'НЕТ'}"
        )

    # Диагностика артикулов из меню
    with_article = sum(1 for i in menu_map.values() if i.get("article"))
    sample = [(i.get("article"), i.get("name")) for i in menu_map.values() if i.get("article")][:5]
    logger.info(f"iiko артикулы из меню: {with_article}/{len(menu_map)} блюд. Примеры: {sample}")

    # ── Шаг 2: Номенклатура — артикулы ───────────────────────────────────────
    uuid_to_sku = {}
    try:
        nom = cloud.get_nomenclature(org_id)
        for prod in nom.get("products") or []:
            pid = prod.get("id") or ""
            num = prod.get("num") or prod.get("code") or ""
            if pid and num:
                uuid_to_sku[pid] = str(num).strip()
        logger.info(f"Nomenclature: {len(uuid_to_sku)} артикулов")
    except Exception as e:
        logger.warning(f"Номенклатура: {e}")
        result["errors"].append(f"Nomenclature: {e}")

    # ── Шаг 3: iiko Server — состав + себестоимость ──────────────────────────
    server_composition = {}
    cost_by_name = {}
    if server_url and server_login:
        server = None
        try:
            server = IikoServerClient(server_url, server_login, server_password)

            # Состав блюд — из технологических карт (getTree, раскрытых до сырья).
            # Фолбэк — description продукта. Запросы техкарт независимы и I/O-bound,
            # поэтому тянем их пулом потоков: последовательно ~269 запросов не
            # укладываются в таймаут веб-сервера.
            server_products = server.get_products()
            products_by_id = {sp.get("id"): sp for sp in server_products if sp.get("id")}
            dish_ids = [pid for pid in menu_map if pid in products_by_id]

            def _fetch_composition(pid):
                try:
                    charts = server.get_assembly_tree(pid)
                    return pid, _composition_from_tree(pid, charts, products_by_id)
                except Exception as e:
                    logger.debug(f"Техкарта {menu_map.get(pid, {}).get('name', pid)}: {e}")
                    return pid, ""

            comp_from_chart = 0
            with ThreadPoolExecutor(max_workers=COMPOSITION_WORKERS) as ex:
                for pid, comp in ex.map(_fetch_composition, dish_ids):
                    if comp:
                        comp_from_chart += 1
                    else:
                        sp = products_by_id.get(pid)
                        comp = _parse_description(sp.get("description")) if sp else ""
                    if comp:
                        server_composition[pid] = comp
            logger.info(
                f"iiko Server: состав для {len(server_composition)} блюд "
                f"(из техкарт: {comp_from_chart}, из description: "
                f"{len(server_composition) - comp_from_chart})"
            )

            # Себестоимость из OLAP-отчёта
            try:
                raw_report = server.get_cost_report()
                cost_by_name = _parse_cost_report(raw_report)
                logger.info(f"OLAP себестоимость: {len(cost_by_name)} блюд")
                sample_keys = list(cost_by_name.keys())[:8]
                logger.info(f"OLAP примеры названий: {sample_keys}")
            except Exception as e:
                logger.warning(f"OLAP отчёт себестоимости: {e}")
                result["errors"].append(f"OLAP себестоимость: {e}")

            server.logout()
        except Exception as e:
            logger.warning(f"iiko Server: {e}")
            result["errors"].append(f"iiko Server: {e}")
            if server:
                try:
                    server.logout()
                except Exception:
                    pass

    # ── Шаг 4: Артикулы ──────────────────────────────────────────────────────
    iiko_skus_in_menu = set()
    iiko_uuid_to_sku  = {}
    for uuid in menu_map:
        sku = uuid_to_sku.get(uuid, uuid)
        iiko_skus_in_menu.add(sku)
        iiko_uuid_to_sku[uuid] = sku

    # ── Шаг 5: Удаление ──────────────────────────────────────────────────────
    # Защита: блюда, используемые в рационах или подгруппах на замену, НЕ удаляем,
    # даже если их артикул пропал из меню iiko.
    from .models import RationSlot as _RationSlot, SwapItem as _SwapItem
    used_product_ids = set(
        _RationSlot.objects.filter(product__isnull=False).values_list("product_id", flat=True)
    ) | set(
        _SwapItem.objects.values_list("product_id", flat=True)
    )

    # АВТО-УДАЛЕНИЕ ОТКЛЮЧЕНО.
    # Раньше блюда, пропавшие из меню iiko, удалялись автоматически — это приводило
    # к потере блюд в каталоге, обнулению слотов рационов и удалению позиций на замену
    # (например, когда в iiko пересоздавали подгруппы и у блюд менялись ID).
    # Теперь синхронизация НИЧЕГО не удаляет — только фиксирует «кандидатов» в лог.
    # Удалять ненужные блюда можно вручную через админку.
    delete_candidates = Product.objects.filter(
        iiko_sku__isnull=False
    ).exclude(iiko_sku__in=iiko_skus_in_menu).exclude(pk__in=used_product_ids)

    cand_count = delete_candidates.count()
    if cand_count > 0:
        names = list(delete_candidates.values_list("name", flat=True))
        logger.warning(
            f"Кандидаты на удаление (НЕ удалены, авто-удаление отключено): "
            f"{cand_count}: {names}"
        )
        result["delete_candidates"] = cand_count
    result["deleted"] = 0

    # ── Шаг 6: Предзагружаем существующие продукты ───────────────────────────
    existing_by_sku = {
        p.iiko_sku: p
        for p in Product.objects.filter(iiko_sku__in=iiko_skus_in_menu)
    }
    existing_by_uuid = {
        p.iiko_id: p
        for p in Product.objects.filter(
            iiko_id__in=set(menu_map.keys())
        ).exclude(iiko_sku__isnull=False)
    }

    # Индекс по АРТИКУЛУ — устойчивое сопоставление, даже если внутренний код iiko
    # поменялся (напр. блюдо пересоздали в новой подгруппе с тем же артикулом).
    # Берём только артикулы, уникальные И в меню, И в базе — чтобы не перепутать блюда.
    from collections import Counter as _Counter
    _menu_art_counts = _Counter(
        (info.get("article") or "").strip()
        for info in menu_map.values()
        if (info.get("article") or "").strip()
    )
    _unique_menu_articles = {a for a, n in _menu_art_counts.items() if n == 1}
    existing_by_article = {}
    _dup_articles = set()
    if _unique_menu_articles:
        for p in Product.objects.filter(article__in=_unique_menu_articles):
            a = (p.article or "").strip()
            if not a:
                continue
            if a in existing_by_article:
                _dup_articles.add(a)          # артикул задвоен в базе — не сопоставляем по нему
            else:
                existing_by_article[a] = p
        for a in _dup_articles:
            existing_by_article.pop(a, None)

    article_matched = 0

    now = dj_timezone.now()

    # Нормализованные словари себестоимости для устойчивого сопоставления
    cost_norm = {}
    cost_norm_nosuffix = {}
    for k, v in cost_by_name.items():
        cost_norm.setdefault(_norm_name(k), v)
        cost_norm_nosuffix.setdefault(_norm_name_nosuffix(k), v)
    cost_matched = 0
    cost_unmatched = []

    # Сопоставление категорий: код + редактируемое из админки
    label_to_key = _build_label_to_key()

    # ── Шаг 7: Создаём / обновляем ───────────────────────────────────────────
    for uuid, menu_info in menu_map.items():
        sku = iiko_uuid_to_sku.get(uuid, uuid)

        try:
            # 1) по артикулу (стабильно), 2) по коду iiko (запасной вариант)
            _art = (menu_info.get("article") or "").strip()
            product = None
            if _art and _art in existing_by_article:
                product = existing_by_article[_art]
                article_matched += 1
            if product is None:
                product = existing_by_sku.get(sku) or existing_by_uuid.get(uuid)
            is_new = product is None

            cat_display, matched_slot_key = _pick_category(menu_info, label_to_key)

            # Артикул: сначала из меню, иначе из номенклатуры (num), но НЕ uuid
            article = menu_info.get("article") or ""
            if not article:
                nom_num = uuid_to_sku.get(uuid)
                if nom_num and nom_num != uuid:
                    article = nom_num

            new_fields = {
                "name":           menu_info["name"],
                "article":        article,
                "iiko_category":  cat_display,
                "iiko_sku":       sku,
                "iiko_id":        uuid,
            }
            if menu_info.get("packing"):
                new_fields["packing"] = menu_info["packing"]
            if menu_info.get("weight") is not None:
                new_fields["net_weight"] = menu_info["weight"] / 1000
            for src, dst in [
                ("kcal",      "kcal_per_100"),
                ("protein",   "protein"),
                ("fat",       "fat"),
                ("carbs",     "carbs"),
                ("kj_100",    "kj_per_100"),
                ("kcal_s",    "kcal_per_serving"),
                ("protein_s", "protein_per_serving"),
                ("fat_s",     "fat_per_serving"),
                ("carbs_s",   "carbs_per_serving"),
                ("kj_s",      "kj_per_serving"),
            ]:
                if menu_info.get(src) is not None:
                    new_fields[dst] = menu_info[src]
            if uuid in server_composition:
                new_fields["composition"] = server_composition[uuid]

            # Себестоимость: точное → по нормализованному имени → без суффикса "(1порц)"
            if cost_by_name:
                product_name = menu_info["name"]
                cost_val = cost_by_name.get(product_name)
                if cost_val is None:
                    cost_val = cost_norm.get(_norm_name(product_name))
                if cost_val is None:
                    cost_val = cost_norm_nosuffix.get(_norm_name_nosuffix(product_name))
                if cost_val is not None:
                    # Decimal, а не float: поле DecimalField, и цена продажи
                    # считается в Decimal — смешение типов ломает сохранение
                    new_fields["cost"] = Decimal(str(round(cost_val, 2)))
                    cost_matched += 1
                else:
                    cost_unmatched.append(product_name)

            if is_new:
                new_fields["iiko_synced_at"] = now
                product = Product.objects.create(**new_fields)
                result["created"] += 1
            else:
                changed, changed_fields = _fields_changed(product, new_fields)
                if changed:
                    for k, v in new_fields.items():
                        setattr(product, k, v)
                    product.iiko_synced_at = now
                    product.save()
                    result["updated"] += 1
                    logger.debug(f"Обновлён '{menu_info['name']}': {changed_fields}")
                else:
                    result["unchanged"] += 1

            # ── Фото ─────────────────────────────────────────────────────────
            photo_url = menu_info.get("photo_url", "")
            if photo_url and _photo_url_changed(product, photo_url):
                photo_data, ext = _download_photo(photo_url)
                if photo_data:
                    url_hash = hashlib.md5(photo_url.encode()).hexdigest()[:8]
                    filename = f"iiko_{sku}_{url_hash}{ext}"
                    if product.photo:
                        try:
                            product.photo.delete(save=False)
                        except Exception:
                            pass
                    product.photo.save(filename, ContentFile(photo_data), save=True)

            # ── Аллергены ─────────────────────────────────────────────────────
            # get_or_create каждого аллергена по имени, затем синхронизируем M2M
            allergen_names = menu_info.get("allergen_names") or []
            if allergen_names:
                allergen_objs = []
                for a_name in allergen_names:
                    allergen, _ = Allergen.objects.get_or_create(name=a_name)
                    allergen_objs.append(allergen)
                # Полная замена — устанавливаем ровно тех что пришли из iiko
                product.allergens.set(allergen_objs)
            else:
                # Если в iiko аллергенов нет — очищаем
                product.allergens.clear()

            # ── Категория ─────────────────────────────────────────────────────
            if matched_slot_key:
                try:
                    meal_cat = MealCategory.objects.get(key=matched_slot_key)
                    product.meal_categories.set([meal_cat])
                except MealCategory.DoesNotExist:
                    logger.debug(f"MealCategory '{matched_slot_key}' не найдена в БД")

        except Exception as e:
            msg = f"'{menu_info.get('name', uuid)}': {e}"
            logger.error(f"Ошибка: {msg}")
            result["errors"].append(msg)
            result["skipped"] += 1

    _last_sync_time = time.time()

    if cost_by_name:
        logger.info(
            f"Себестоимость: сопоставлено {cost_matched}, "
            f"не найдено {len(cost_unmatched)}. "
            f"Без цены: {cost_unmatched[:15]}"
        )

    logger.info(f"Сопоставлено по артикулу: {article_matched} блюд")
    logger.info(
        f"Готово — создано: {result['created']}, "
        f"обновлено: {result['updated']}, "
        f"без изменений: {result['unchanged']}, "
        f"удалено: {result['deleted']}, "
        f"пропущено: {result['skipped']}"
    )
    return result