"""Выгрузка всей базы одним JSON — для общей базы Olive в Supabase.

Внешний сборщик раз в сутки забирает GET /api/export/ с заголовком
`Authorization: Bearer <EXPORT_API_TOKEN>` и раскладывает таблицы у себя.
Контракт описан в docs/export-api.md: при любом изменении формата поднимайте
SCHEMA_VERSION и правьте документ — на той стороне парсер пишется по нему.

Отдаём плоские таблицы со ссылками по id, как они лежат в БД: так их проще
всего залить в Postgres. Пользователи, права и логи синхронизаций не отдаются.
Старые рационы (Ration) тоже — вкладку убрали, данные заморожены.
"""

import hmac

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import (
    CATALOG_ONLY_KEYS, SLOT_TYPES,
    CalorieCategory, CalorieCategoryMeal, ClaudeRation, ClaudeRationGroup,
    ClaudeRationSlot, IikoCategoryMap, Material, MealTime, Product,
    SwapGroup, SwapItem,
)

SCHEMA_VERSION = 1
SOURCE = "olive-nutri-baza"


def _num(value):
    return None if value is None else float(value)


def _dt(value):
    return value.isoformat() if value else None


def _username(user):
    return user.get_username() if user else None


def _check_token(request):
    """None — доступ есть, иначе готовый ответ с ошибкой."""
    expected = getattr(settings, "EXPORT_API_TOKEN", "")
    if not expected:
        # Пустой токен не должен открывать выгрузку всем подряд
        return JsonResponse({"error": "export API is not configured"}, status=503)
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), expected):
        return JsonResponse({"error": "invalid or missing token"}, status=401)
    return None


def _product_row(p, base_url):
    return {
        "id": p.pk,
        "name": p.name,
        "article": p.article or None,
        "iiko_id": p.iiko_id,
        "iiko_sku": p.iiko_sku,
        "iiko_category": p.iiko_category,
        "meal_categories": sorted(c.key for c in p.meal_categories.all()),
        "packing": p.packing,
        # в БД масса нетто хранится в кг
        "net_weight_g": _num(p.net_weight * 1000) if p.net_weight is not None else None,
        "cost": _num(p.cost),
        "sale_price": _num(p.sale_price),
        "sale_price_manual": p.sale_price_manual,
        "markup": _num(p.markup),
        "markup_pct": round(p.markup_pct, 2) if p.markup_pct is not None else None,
        "composition": p.composition_clean or None,
        "composition_raw": p.composition,
        "protein_100": _num(p.protein),
        "fat_100": _num(p.fat),
        "carbs_100": _num(p.carbs),
        "kcal_100": _num(p.kcal_per_100),
        "kj_100": _num(p.kj_per_100),
        "protein_serving": _num(p.protein_per_serving),
        "fat_serving": _num(p.fat_per_serving),
        "carbs_serving": _num(p.carbs_per_serving),
        "kcal_serving": _num(p.kcal_per_serving),
        "kj_serving": _num(p.kj_per_serving),
        "photo_url": f"{base_url}{p.photo.url}" if p.photo else None,
        "iiko_synced_at": _dt(p.iiko_synced_at),
    }


def build_export(base_url=""):
    products = Product.objects.prefetch_related("meal_categories").order_by("pk")

    tables = {
        "meal_categories": [
            {"key": key, "name": name, "for_rations": key not in CATALOG_ONLY_KEYS}
            for key, name in SLOT_TYPES
        ],
        "meal_times": [
            {"id": m.pk, "name": m.name, "icon": m.icon, "order": m.order}
            for m in MealTime.objects.order_by("pk")
        ],
        "products": [_product_row(p, base_url) for p in products],
        "calorie_categories": [
            {
                "id": c.pk, "name": c.name, "kcal": c.kcal,
                "kcal_min": c.kcal_min, "kcal_max": c.kcal_max,
                "protein_min": c.protein_min, "protein_max": c.protein_max,
                "fat_min": c.fat_min, "fat_max": c.fat_max,
                "carbs_min": c.carbs_min, "carbs_max": c.carbs_max,
                "order": c.order,
                "created_at": _dt(c.created_at), "updated_at": _dt(c.updated_at),
            }
            for c in CalorieCategory.objects.order_by("pk")
        ],
        "calorie_category_meals": [
            {
                "id": m.pk, "calorie_category_id": m.category_id,
                "meal_time_id": m.meal_time_id, "order": m.order,
            }
            for m in CalorieCategoryMeal.objects.order_by("pk")
        ],
        "ration_groups": [
            {
                "id": g.pk, "name": g.name, "description": g.description,
                "shared_editing": g.shared_editing,
                "created_by": _username(g.created_by),
                "created_at": _dt(g.created_at),
            }
            for g in ClaudeRationGroup.objects.select_related("created_by").order_by("pk")
        ],
        "rations": [
            {
                "id": r.pk, "group_id": r.group_id, "name": r.name,
                "kcal": r.kcal_category, "wishes": r.wishes, "notes": r.notes,
                "order": r.order, "created_by": _username(r.created_by),
                "created_at": _dt(r.created_at), "updated_at": _dt(r.updated_at),
            }
            for r in ClaudeRation.objects.select_related("created_by").order_by("pk")
        ],
        "ration_slots": [
            {
                "id": s.pk, "ration_id": s.ration_id, "meal_time_id": s.meal_time_id,
                "slot_type": s.slot_type, "product_id": s.product_id, "order": s.order,
            }
            for s in ClaudeRationSlot.objects.order_by("pk")
        ],
        "swap_groups": [
            {"id": g.pk, "name": g.name, "order": g.order, "created_at": _dt(g.created_at)}
            for g in SwapGroup.objects.order_by("pk")
        ],
        "swap_items": [
            {
                "id": i.pk, "swap_group_id": i.swap_group_id,
                "product_id": i.product_id, "order": i.order,
            }
            for i in SwapItem.objects.order_by("pk")
        ],
        "materials": [
            {"id": m.pk, "article": m.article or None, "name": m.name,
             "unit": m.unit, "order": m.order}
            for m in Material.objects.order_by("pk")
        ],
        "iiko_category_map": [
            {"id": m.pk, "iiko_name": m.iiko_name, "slot_key": m.slot_key}
            for m in IikoCategoryMap.objects.order_by("pk")
        ],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "generated_at": timezone.now().isoformat(),
        "counts": {name: len(rows) for name, rows in tables.items()},
        **tables,
    }


@require_GET
def export_all(request):
    denied = _check_token(request)
    if denied:
        return denied
    base_url = getattr(settings, "EXPORT_PUBLIC_BASE_URL", "").rstrip("/")
    return JsonResponse(build_export(base_url), json_dumps_params={"ensure_ascii": False})
