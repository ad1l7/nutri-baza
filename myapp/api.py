"""Каталог блюд для внешних систем — только чтение.

Этикетки для нескольких заказчиков печатает ERP, а данные блюд Olive живут
здесь и приезжают из iiko. Поэтому наружу отдаётся ровно то, из чего состоит
этикетка: название, состав, аллергены, БЖУ, масса.

Чего здесь намеренно нет:
  · реквизитов производителя (ТОО, адрес, СТ, ISO) — они принадлежат тому,
    кто печатает, а не блюду: у следующего заказчика они будут свои;
  · срока хранения, размеров наклейки, скорости и плотности печати — это
    настройки печати, а не свойства блюда.

Доступ — по токену LABEL_API_TOKEN в заголовке X-Label-Token. Проверяет его
LoginRequiredMiddleware для всего /api/ целиком, а не декоратор на вьюхе:
так новую ручку нельзя открыть наружу, забыв её повесить.
"""
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .labels import _clean_name
from .models import Product


def _num(value, digits=2):
    """Decimal → число для JSON. None остаётся None: «не заполнено» и 0 — разное."""
    if value is None:
        return None
    return round(float(value), digits)


def _product_json(product):
    return {
        "id": product.pk,
        "article": product.article or "",
        # name — как в каталоге, name_print — очищенное от служебных хвостов
        # iiko («ПП* Упак», «(1порц)»); на этикетку идёт второе.
        "name": product.name,
        "name_print": _clean_name(product.name),
        "composition": product.composition_clean,
        "allergens": [a.name for a in product.allergens.all()],
        # net_weight хранится в килограммах, на этикетке — граммы
        "net_weight_g": _num(product.net_weight * 1000, 1) if product.net_weight is not None else None,
        "nutrition_per_serving": {
            "protein": _num(product.protein_per_serving),
            "fat": _num(product.fat_per_serving),
            "carbs": _num(product.carbs_per_serving),
            "kcal": _num(product.kcal_per_serving),
            "kj": _num(product.kj_per_serving),
        },
        "nutrition_per_100g": {
            "protein": _num(product.protein),
            "fat": _num(product.fat),
            "carbs": _num(product.carbs),
            "kcal": _num(product.kcal_per_100),
            "kj": _num(product.kj_per_100),
        },
        "synced_at": product.iiko_synced_at.isoformat() if product.iiko_synced_at else None,
    }


def _queryset():
    """Блюда, пригодные для печати: без состава этикетку не сделать.
    Тот же отбор, что на вкладке «Этикетки»."""
    return (
        Product.objects
        .exclude(composition_clean="")
        .prefetch_related("allergens")
        .order_by("name")
    )


@require_GET
def label_products(request):
    """Весь каталог одним ответом — ERP забирает его целиком и кладёт себе.
    Блюд немного, разбивать на страницы нечего."""
    items = [_product_json(p) for p in _queryset()]
    return JsonResponse({"source": "olive", "count": len(items), "results": items})


@require_GET
def label_product(request, pk):
    product = _queryset().filter(pk=pk).first()
    if product is None:
        return JsonResponse({"error": "not_found"}, status=404)
    return JsonResponse(_product_json(product))
