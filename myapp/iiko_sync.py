"""
iiko_sync.py — умная синхронизация продуктов из iiko в O-Live.

Ключ синхронизации: артикул (num) из iiko — поле iiko_sku в Product.

Логика обновления:
  - Новые блюда (нет в БД) → создаём + скачиваем фото
  - Существующие блюда → сравниваем поля, обновляем ТОЛЬКО если что-то изменилось
  - Фото → скачиваем только если URL изменился или фото нет
  - Аллергены → берём из item.allergens, get_or_create по имени
  - Удалённые из iiko → удаляем из БД
"""

import re
import time
import hashlib
import requests
import logging
import json as _json
import os
from django.utils import timezone as dj_timezone
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# ── Защита от блокировки ──────────────────────────────────────────────────────
RATE_LIMIT_DELAY  = 0.2
MAX_RETRIES       = 3
RETRY_DELAY       = 5
MIN_SYNC_INTERVAL = 30

_last_sync_time = 0

# ── Точное совпадение название группы iiko → ключ SLOT_TYPES ─────────────────
_SLOT_LABEL_TO_KEY = {
    'Завтрак 250–350 ккал':        'breakfast_250',
    'Завтрак 400–500 ккал':        'breakfast_400',
    'Второе 400–500 ккал':         'second_400',
    'Второе 500–600 ккал':         'second_500',
    'Суп 200 ккал':                'soup_200',
    'Суп 300 ккал':                'soup_300',
    'Салат 150–250 ккал':          'salad_150',
    'Салат 250–350 ккал':          'salad_250',
    'Выпечка/Десерт 100–250 ккал': 'dessert_100',
    'Выпечка/Десерт 300–350 ккал': 'dessert_300',
    'Смузи 100–150 ккал':          'smoothie',
    'Сэндвич 300–350 ккал':        'sandwich',
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


def _pick_category(menu_info: dict) -> tuple:
    """Блюдо может входить сразу в несколько категорий внешнего меню
    (например, ещё в техническую категорию типа 'ПП Упак').
    Возвращает (название_категории_для_отображения, slot_key_или_None) —
    выбираем первую категорию, совпавшую с SLOT_TYPES, иначе первую попавшуюся."""
    cat_names = menu_info.get("category_names") or []
    if not cat_names and menu_info.get("category_name"):
        cat_names = [menu_info["category_name"]]

    for cn in cat_names:
        cn = (cn or "").strip()
        if not cn:
            continue
        slot_key = _SLOT_LABEL_TO_KEY_NORM.get(_normalize_label(cn))
        if slot_key:
            return cn, slot_key

    first = next((cn.strip() for cn in cat_names if cn and cn.strip()), "")
    return first, None

_COMPARE_FIELDS = [
    "name", "iiko_category", "packing", "net_weight",
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

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._token = None

    def _get_token(self) -> str:
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
            "aggregateFields": ["Sum.Incoming"],
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

def _parse_cost_report(report_data: dict) -> dict:
    """Возвращает {product_name: cost} из ответа OLAP-отчёта iiko Server."""
    costs = {}
    columns = report_data.get("columnNames") or report_data.get("columns") or []
    rows = report_data.get("data") or []

    if not rows:
        return costs

    # Формат 1: список имён колонок + список строк-списков
    if columns:
        name_idx = next((i for i, c in enumerate(columns) if "Product.Name" in str(c)), None)
        cost_idx = next((i for i, c in enumerate(columns) if "Sum.Incoming" in str(c)), None)
        if name_idx is not None and cost_idx is not None:
            for row in rows:
                if isinstance(row, list) and len(row) > max(name_idx, cost_idx):
                    try:
                        name = str(row[name_idx]).strip()
                        cost = float(row[cost_idx])
                        if name:
                            costs[name] = cost
                    except (TypeError, ValueError):
                        pass
        return costs

    # Формат 2: строки-словари
    if rows and isinstance(rows[0], dict):
        for row in rows:
            name = str(row.get("Product.Name") or "").strip()
            try:
                cost = float(row.get("Sum.Incoming") or 0)
                if name:
                    costs[name] = cost
            except (TypeError, ValueError):
                pass

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

    cloud = IikoCloudClient(cloud_api_key)

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

            # Состав блюд
            server_products = server.get_products()
            menu_ids = set(menu_map.keys())
            for sp in server_products:
                pid = sp.get("id") or ""
                if pid not in menu_ids:
                    continue
                desc = _parse_description(sp.get("description"))
                if desc:
                    server_composition[pid] = desc
                time.sleep(RATE_LIMIT_DELAY)
            logger.info(f"iiko Server: состав для {len(server_composition)} блюд")

            # Себестоимость из OLAP-отчёта
            try:
                raw_report = server.get_cost_report()
                cost_by_name = _parse_cost_report(raw_report)
                logger.info(f"OLAP себестоимость: {len(cost_by_name)} блюд")
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
    products_to_delete = Product.objects.filter(
        iiko_sku__isnull=False
    ).exclude(iiko_sku__in=iiko_skus_in_menu)

    deleted_count = products_to_delete.count()
    if deleted_count > 0:
        if deleted_count > 100:
            result["errors"].append(
                f"Попытка удалить {deleted_count} продуктов — превышен лимит 100. "
                f"Проверь IIKO_EXTERNAL_MENU_ID."
            )
            return result
        names = list(products_to_delete.values_list("name", flat=True))
        logger.info(f"Удаляем {deleted_count}: {names}")
        products_to_delete.delete()
        result["deleted"] = deleted_count

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

    now = dj_timezone.now()

    # ── Шаг 7: Создаём / обновляем ───────────────────────────────────────────
    for uuid, menu_info in menu_map.items():
        sku = iiko_uuid_to_sku.get(uuid, uuid)

        try:
            product = existing_by_sku.get(sku) or existing_by_uuid.get(uuid)
            is_new = product is None

            cat_display, matched_slot_key = _pick_category(menu_info)

            new_fields = {
                "name":           menu_info["name"],
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

            # Себестоимость: ищем по имени (сначала точное, потом без учёта регистра)
            if cost_by_name:
                product_name = menu_info["name"]
                cost_val = cost_by_name.get(product_name)
                if cost_val is None:
                    name_upper = product_name.upper()
                    cost_val = next(
                        (v for k, v in cost_by_name.items() if k.upper() == name_upper),
                        None,
                    )
                if cost_val is not None:
                    new_fields["cost"] = round(cost_val, 2)

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

    logger.info(
        f"Готово — создано: {result['created']}, "
        f"обновлено: {result['updated']}, "
        f"без изменений: {result['unchanged']}, "
        f"удалено: {result['deleted']}, "
        f"пропущено: {result['skipped']}"
    )
    return result