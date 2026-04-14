"""
iiko_sync.py — синхронизация продуктов из iiko в O-Live.

Источники данных:
  - iikoCloud API (/api/2/menu/by_id) — название, категория, КБЖУ
  - iiko Server API (/resto/api/v2/...) — состав (техкарты), кратность

Поля в Product:
  iiko_id          — UUID блюда (ключ синхронизации)
  iiko_category    — название категории из iiko
  iiko_synced_at   — время последней синхронизации
  name             — наименование
  kcal_per_100     — ккал на 100г
  protein          — белки на 100г
  fat              — жиры на 100г
  carbs            — углеводы на 100г
  composition      — состав (из техкарты iiko Server)
  packing          — кратность (единица измерения из iiko Server)
"""

import requests
import logging
from datetime import date, datetime, timezone
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# iikoCloud клиент
# ──────────────────────────────────────────────────────────────────────────────

class IikoCloudClient:
    BASE = "https://api-ru.iiko.services"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._token = None

    def _get_token(self) -> str:
        resp = requests.post(
            f"{self.BASE}/api/1/access_token",
            json={"apiLogin": self.api_key},
            timeout=20,
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        return self._token

    def _headers(self) -> dict:
        if not self._token:
            self._get_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def get_organizations(self) -> list:
        resp = requests.post(
            f"{self.BASE}/api/1/organizations",
            json={"returnAdditionalInfo": False},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("organizations", [])

    def get_nomenclature(self, org_id: str) -> dict:
        """Возвращает полную номенклатуру (продукты + категории)."""
        resp = requests.post(
            f"{self.BASE}/api/1/nomenclature",
            json={"organizationId": org_id, "startRevision": 0},
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_external_menus(self) -> list:
        """Возвращает список внешних меню организации."""
        resp = requests.post(
            f"{self.BASE}/api/2/menu",
            json={},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("externalMenus", []) or []

    def get_menu_by_id(self, menu_id: str, org_id: str) -> dict:
        """Возвращает полное внешнее меню с КБЖУ."""
        resp = requests.post(
            f"{self.BASE}/api/2/menu/by_id",
            json={
                "externalMenuId": menu_id,
                "organizationIds": [org_id],
                "priceCategoryId": "00000000-0000-0000-0000-000000000000",
                "version": 2,
            },
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# iiko Server клиент
# ──────────────────────────────────────────────────────────────────────────────

class IikoServerClient:
    def __init__(self, server_url: str, login: str, password: str):
        # server_url например "http://localhost:8080"
        self.base = server_url.rstrip("/")
        self.login = login
        self.password = password
        self._token = None

    def _get_token(self) -> str:
        resp = requests.get(
            f"{self.base}/resto/api/v2/auth/login",
            params={"login": self.login, "pass": self.password},
            timeout=20,
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
                    f"{self.base}/resto/api/v2/auth/logout",
                    params={"key": self._token},
                    timeout=10,
                )
            except Exception:
                pass

    def get_products(self) -> list:
        """Список всей номенклатуры (блюда, заготовки и т.д.)."""
        resp = requests.get(
            f"{self.base}/resto/api/v2/entities/products/list",
            params=self._params({"includeDeleted": "false"}),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_assembly_chart(self, product_id: str) -> dict | None:
        """Техкарта (первый уровень) для конкретного блюда."""
        today = date.today().isoformat()
        try:
            resp = requests.get(
                f"{self.base}/resto/api/v2/assemblyCharts/getAssembled",
                params=self._params({"productId": product_id, "date": today}),
                timeout=20,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            charts = data.get("assemblyCharts") or []
            return charts[0] if charts else None
        except Exception as e:
            logger.warning(f"Техкарта для {product_id}: {e}")
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Парсер внешнего меню iikoCloud → плоский список блюд
# ──────────────────────────────────────────────────────────────────────────────

def _extract_items_from_menu(menu_data: dict) -> list[dict]:
    items = []

    def _parse_item(item: dict, cat_name: str):
        product_id = item.get("itemId") or item.get("id") or ""
        name = item.get("name") or ""
        if not product_id or not name:
            return

        sizes = item.get("itemSizes") or []
        size = sizes[0] if sizes else {}

        nutr = size.get("nutritionPerHundredGrams") or {}
        if not nutr:
            nutritions = size.get("nutritions") or []
            nutr = nutritions[0] if nutritions else {}

        weight_grams = _safe_float(size.get("portionWeightGrams"))

        # КБЖУ на 100г
        kcal_100    = _safe_float(nutr.get("energy"))
        protein_100 = _safe_float(nutr.get("proteins"))
        fat_100     = _safe_float(nutr.get("fats"))
        carbs_100   = _safe_float(nutr.get("carbs"))
        kj_100      = round(kcal_100 * 4.184, 2) if kcal_100 is not None else None

        # КБЖУ на порцию = значение на 100г * вес_порции / 100
        def per_serving(val):
            if val is not None and weight_grams:
                return round(val * weight_grams / 100, 2)
            return None

        items.append({
            "id": product_id,
            "name": name,
            "category_name": cat_name,
            "packing": item.get("measureUnit") or "",
            "kcal":       kcal_100,
            "protein":    protein_100,
            "fat":        fat_100,
            "carbs":      carbs_100,
            "kj_100":     kj_100,
            "kcal_s":     per_serving(kcal_100),
            "protein_s":  per_serving(protein_100),
            "fat_s":      per_serving(fat_100),
            "carbs_s":    per_serving(carbs_100),
            "kj_s":       per_serving(kj_100),
            "weight":     weight_grams,
            })  

    def walk_categories(categories: list, parent_name: str = ""):
        for cat in categories or []:
            cat_name = cat.get("name") or parent_name or ""
            walk_categories(cat.get("childCategories") or [], cat_name)
            for item in cat.get("items") or []:
                _parse_item(item, cat_name)

    walk_categories(menu_data.get("itemCategories") or [])

    if not items:
        for pcat in menu_data.get("productCategories") or []:
            cat_name = pcat.get("name") or ""
            for item in pcat.get("items") or []:
                _parse_item(item, cat_name)

    return items

def _safe_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


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
    from .models import Product, MealCategory, SLOT_LABELS

    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    # ── 1. Получаем блюда из внешнего меню iikoCloud ──────────────────────────
    cloud = IikoCloudClient(cloud_api_key)
    try:
        menu_data = cloud.get_menu_by_id(external_menu_id, org_id)
    except Exception as e:
        result["errors"].append(f"iikoCloud: не удалось получить меню — {e}")
        return result

    cloud_items = _extract_items_from_menu(menu_data)
    if not cloud_items:
        result["errors"].append("iikoCloud: меню получено, но блюд не найдено. Проверь external_menu_id.")
        return result

    logger.info(f"iikoCloud: найдено {len(cloud_items)} блюд в меню {external_menu_id}")

    # ── 2. Получаем данные из iiko Server (состав) ────────────────────────────
    server_data = {}
    if server_url and server_login:
        try:
            server = IikoServerClient(server_url, server_login, server_password)
            server_products = server.get_products()
            names_map = {sp.get("id"): sp.get("name", "") for sp in server_products}

            menu_ids = {item["id"] for item in cloud_items}
            for pid in menu_ids:
                chart = server.get_assembly_chart(pid)
                if not chart:
                    continue
                parts = []
                for ing in chart.get("items") or []:
                    ing_id = ing.get("productId") or ""
                    amount_out = ing.get("amountOut") or ing.get("amount") or 0
                    ing_name = names_map.get(ing_id, "")
                    if ing_name and amount_out:
                        parts.append(f"{ing_name} — {float(amount_out)*1000:.0f}г")
                if parts:
                    server_data[pid] = {"composition": ", ".join(parts)}
            server.logout()
        except Exception as e:
            logger.warning(f"iiko Server недоступен: {e}")
            result["errors"].append(f"iiko Server: {e} (синхронизация продолжена без состава)")

    # ── 3. Синхронизируем с базой ─────────────────────────────────────────────
    now = dj_timezone.now()

    for item in cloud_items:
        iiko_id = item["id"]
        try:
            product = None
            try:
                product = Product.objects.get(iiko_id=iiko_id)
            except Product.DoesNotExist:
                pass

            srv = server_data.get(iiko_id, {})

            fields = {
                "name":          item["name"],
                "iiko_category": item["category_name"],
                "iiko_synced_at": now,
            }

            # Кратность из iikoCloud
            if item.get("packing"):
                fields["packing"] = item["packing"]

            # КБЖУ на 100г
            if item.get("kcal") is not None:
                fields["kcal_per_100"] = item["kcal"]
            if item.get("protein") is not None:
                fields["protein"] = item["protein"]
            if item.get("fat") is not None:
                fields["fat"] = item["fat"]
            if item.get("carbs") is not None:
                fields["carbs"] = item["carbs"]

            # КБЖУ на порцию
            if item.get("kcal_s") is not None:
                fields["kcal_per_serving"] = item["kcal_s"]
            if item.get("protein_s") is not None:
                fields["protein_per_serving"] = item["protein_s"]
            if item.get("fat_s") is not None:
                fields["fat_per_serving"] = item["fat_s"]
            if item.get("carbs_s") is not None:
                fields["carbs_per_serving"] = item["carbs_s"]

            # Масса нетто (уже в граммах)
            if item.get("weight") is not None:
                fields["net_weight"] = item["weight"] / 1000

            #КДЖ
            if item.get("kj_100") is not None:
                fields["kj_per_100"] = item["kj_100"]
            if item.get("kj_s") is not None:
                fields["kj_per_serving"] = item["kj_s"]
            # Состав из iiko Server
            if srv.get("composition"):
                fields["composition"] = srv["composition"]

            if product:
                for k, v in fields.items():
                    setattr(product, k, v)
                product.save()
                result["updated"] += 1
            else:
                fields["iiko_id"] = iiko_id
                Product.objects.create(**fields)
                result["created"] += 1

        except Exception as e:
            msg = f"Ошибка для '{item.get('name', iiko_id)}': {e}"
            logger.error(msg)
            result["errors"].append(msg)
            result["skipped"] += 1

    logger.info(
        f"Синхронизация завершена: создано {result['created']}, "
        f"обновлено {result['updated']}, пропущено {result['skipped']}"
    )
    return result