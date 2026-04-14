from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
import json
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from .models import (
    Product, Allergen, MealCategory,
    RationGroup, Ration, RationSlot,
    RationTemplate, RationTemplateSlot,
    SLOT_TYPES, SLOT_ORDER, SLOT_LABELS, KCAL_CATEGORIES,
)

# ── Каталог продуктов ─────────────────────────────────────────────────────────

def product_list(request):
    products = Product.objects.prefetch_related("meal_categories", "allergens").all()
    all_meal_categories = MealCategory.objects.all()
    all_allergens = Allergen.objects.all()

    search                   = request.GET.get("search", "").strip()
    selected_meal_categories = request.GET.getlist("meal_category")
    selected_allergens       = request.GET.getlist("allergen")
    cost_min = request.GET.get("cost_min", "")
    cost_max = request.GET.get("cost_max", "")
    kcal_min      = request.GET.get("kcal_min", "")
    kcal_max      = request.GET.get("kcal_max", "")
    protein_min   = request.GET.get("protein_min", "")
    protein_max   = request.GET.get("protein_max", "")
    fat_min       = request.GET.get("fat_min", "")
    fat_max       = request.GET.get("fat_max", "")
    carbs_min     = request.GET.get("carbs_min", "")
    carbs_max     = request.GET.get("carbs_max", "")
    kcal_s_min    = request.GET.get("kcal_s_min", "")
    kcal_s_max    = request.GET.get("kcal_s_max", "")
    protein_s_min = request.GET.get("protein_s_min", "")
    protein_s_max = request.GET.get("protein_s_max", "")
    fat_s_min     = request.GET.get("fat_s_min", "")
    fat_s_max     = request.GET.get("fat_s_max", "")
    carbs_s_min   = request.GET.get("carbs_s_min", "")
    carbs_s_max   = request.GET.get("carbs_s_max", "")
    packing       = request.GET.get("packing", "").strip()
    sort_by       = request.GET.get("sort", "name")
    sort_dir      = request.GET.get("dir", "asc")

    if search:
        products = products.filter(Q(name__icontains=search) | Q(composition__icontains=search))
    if selected_meal_categories:
        products = products.filter(meal_categories__key__in=selected_meal_categories).distinct()
    if selected_allergens:
        products = products.filter(allergens__pk__in=selected_allergens).distinct()
    if cost_min: products = products.filter(cost__gte=cost_min)
    if cost_max: products = products.filter(cost__lte=cost_max)
    if kcal_min:      products = products.filter(kcal_per_100__gte=kcal_min)
    if kcal_max:      products = products.filter(kcal_per_100__lte=kcal_max)
    if protein_min:   products = products.filter(protein__gte=protein_min)
    if protein_max:   products = products.filter(protein__lte=protein_max)
    if fat_min:       products = products.filter(fat__gte=fat_min)
    if fat_max:       products = products.filter(fat__lte=fat_max)
    if carbs_min:     products = products.filter(carbs__gte=carbs_min)
    if carbs_max:     products = products.filter(carbs__lte=carbs_max)
    if kcal_s_min:    products = products.filter(kcal_per_serving__gte=kcal_s_min)
    if kcal_s_max:    products = products.filter(kcal_per_serving__lte=kcal_s_max)
    if protein_s_min: products = products.filter(protein_per_serving__gte=protein_s_min)
    if protein_s_max: products = products.filter(protein_per_serving__lte=protein_s_max)
    if fat_s_min:     products = products.filter(fat_per_serving__gte=fat_s_min)
    if fat_s_max:     products = products.filter(fat_per_serving__lte=fat_s_max)
    if carbs_s_min:   products = products.filter(carbs_per_serving__gte=carbs_s_min)
    if carbs_s_max:   products = products.filter(carbs_per_serving__lte=carbs_s_max)
    if packing:
        products = products.filter(packing__icontains=packing)

    sort_map = {
        "name": "name", "net_weight": "net_weight", "cost": "cost",
        "kcal": "kcal_per_100", "protein": "protein", "fat": "fat", "carbs": "carbs",
        "kcal_s": "kcal_per_serving", "protein_s": "protein_per_serving",
        "fat_s": "fat_per_serving", "carbs_s": "carbs_per_serving",
    }
    sort_field = sort_map.get(sort_by, "name")
    if sort_dir == "desc":
        sort_field = f"-{sort_field}"
    products = products.order_by(sort_field)

    total = products.count()
    packings = (
        Product.objects.values_list("packing", flat=True)
        .distinct().exclude(packing__isnull=True).exclude(packing="").order_by("packing")
    )
    selected_allergen_names = list(
        Allergen.objects.filter(pk__in=selected_allergens).values_list("name", flat=True)
    ) if selected_allergens else []

    return render(request, "myapp/product_list.html", {
        "products": products, "total": total,
        "all_meal_categories": all_meal_categories,
        "all_allergens": all_allergens, "packings": packings,
        "selected_meal_categories": selected_meal_categories,
        "selected_allergens": selected_allergens,
        "selected_allergen_names": selected_allergen_names,
        "slot_labels": SLOT_LABELS,
        "filters": {
            "search": search, "cost_min": cost_min, "cost_max": cost_max,
            "kcal_min": kcal_min, "kcal_max": kcal_max,
            "protein_min": protein_min, "protein_max": protein_max,
            "fat_min": fat_min, "fat_max": fat_max,
            "carbs_min": carbs_min, "carbs_max": carbs_max,
            "kcal_s_min": kcal_s_min, "kcal_s_max": kcal_s_max,
            "protein_s_min": protein_s_min, "protein_s_max": protein_s_max,
            "fat_s_min": fat_s_min, "fat_s_max": fat_s_max,
            "carbs_s_min": carbs_s_min, "carbs_s_max": carbs_s_max,
            "packing": packing, "sort": sort_by, "dir": sort_dir,
        },
    })


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, "myapp/product_detail.html", {"product": product})


# ── Вспомогательные константы ─────────────────────────────────────────────────

SLOT_ICONS = {
    'breakfast_250': '🌅', 'breakfast_400': '🌅',
    'second_400': '🍽️',   'second_500': '🍽️',
    'soup_200': '🥣',      'soup_300': '🥣',
    'salad_150': '🥗',     'salad_250': '🥗',
    'dessert_100': '🍰',   'dessert_300': '🍰',
    'smoothie': '🥤',      'sandwich': '🥪',
}

SLOT_COLORS = {
    'breakfast_250': 'orange', 'breakfast_400': 'orange',
    'second_400': 'green',     'second_500': 'green',
    'soup_200': 'blue',        'soup_300': 'blue',
    'salad_150': 'teal',       'salad_250': 'teal',
    'dessert_100': 'pink',     'dessert_300': 'pink',
    'smoothie': 'purple',      'sandwich': 'amber',
}


# ── Шаблоны рационов ──────────────────────────────────────────────────────────



# ── Группы рационов ───────────────────────────────────────────────────────────

def ration_group_list(request):
    groups = RationGroup.objects.prefetch_related("rations__slots__product").all()
    groups_data = []
    for g in groups:
        rations = list(g.rations.all())
        rations_info = []
        for r in rations:
            slots = list(r.slots.select_related("product").order_by("order"))
            total_kcal = sum(
                float(s.product.kcal_per_serving or 0) for s in slots if s.product
            )
            rations_info.append({
                "ration": r,
                "slots": slots,
                "total_kcal": round(total_kcal, 1),
            })
        groups_data.append({
            "group": g,
            "rations_info": rations_info,
            "count": len(rations),
        })
    # Данные шаблонов для превью в модале создания рациона
    tmpl_data = {}
    for kcal, _ in KCAL_CATEGORIES:
        try:
            tmpl = RationTemplate.objects.prefetch_related("slots").get(kcal_category=kcal)
            tmpl_data[kcal] = [s.slot_type for s in tmpl.slots.order_by("order")]
        except RationTemplate.DoesNotExist:
            tmpl_data[kcal] = []

    return render(request, "myapp/ration_group_list.html", {
        "groups_data": groups_data,
        "ration_kcal_choices": KCAL_CATEGORIES,
        "slot_icons": SLOT_ICONS,
        "tmpl_data_json": json.dumps(tmpl_data, ensure_ascii=False),
        "slot_labels_json": json.dumps(SLOT_LABELS, ensure_ascii=False),
    })


def ration_group_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        if name:
            RationGroup.objects.create(name=name, description=description or None)
    return redirect("ration_group_list")


def ration_group_delete(request, group_pk):
    group = get_object_or_404(RationGroup, pk=group_pk)
    if request.method == "POST":
        group.delete()
    return redirect("ration_group_list")


# ── Рационы ───────────────────────────────────────────────────────────────────

def ration_list(request, group_pk):
    return redirect("ration_group_list")


def ration_create(request, group_pk):
    group = get_object_or_404(RationGroup, pk=group_pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        kcal_category = request.POST.get("kcal_category", "")
        notes = request.POST.get("notes", "").strip()
        if name and kcal_category:
            ration = Ration.objects.create(
                group=group, name=name,
                kcal_category=int(kcal_category),
                notes=notes or None,
            )
            # Автоматически добавить слоты из шаблона
            try:
                tmpl = RationTemplate.objects.get(kcal_category=int(kcal_category))
                for tslot in tmpl.slots.order_by("order"):
                    RationSlot.objects.create(
                        ration=ration,
                        slot_type=tslot.slot_type,
                        order=tslot.order,
                    )
            except RationTemplate.DoesNotExist:
                pass
            return redirect("ration_edit", pk=ration.pk)
    return redirect("ration_group_list")


def ration_edit(request, pk):
    ration = get_object_or_404(Ration, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "update_meta":
            ration.name = request.POST.get("name", ration.name).strip()
            ration.kcal_category = int(request.POST.get("kcal_category", ration.kcal_category))
            ration.notes = request.POST.get("notes", "").strip() or None
            ration.save()

        

        elif action == "update_slot":
            slot_id = request.POST.get("slot_id")
            product_id = request.POST.get("product_id") or None
            try:
                slot = RationSlot.objects.get(pk=slot_id, ration=ration)
                slot.product_id = product_id
                slot.save()
            except RationSlot.DoesNotExist:
                pass


        return redirect("ration_edit", pk=pk)

    # GET
    slots = list(ration.slots.select_related("product").order_by("order", "id"))
    slots_with_meta = []
    total_kcal = total_protein = total_fat = total_carbs = 0

    for slot in slots:
        p = slot.product
        kcal    = float(p.kcal_per_serving or 0) if p else 0
        protein = float(p.protein_per_serving or 0) if p else 0
        fat     = float(p.fat_per_serving or 0) if p else 0
        carbs   = float(p.carbs_per_serving or 0) if p else 0
        total_kcal    += kcal
        total_protein += protein
        total_fat     += fat
        total_carbs   += carbs
        slots_with_meta.append({
            "slot": slot,
            "label": SLOT_LABELS.get(slot.slot_type, slot.slot_type),
            "icon": SLOT_ICONS.get(slot.slot_type, "🍴"),
            "color": SLOT_COLORS.get(slot.slot_type, "green"),
            "kcal": round(kcal, 1),
            "protein": round(protein, 1),
            "fat": round(fat, 1),
            "carbs": round(carbs, 1),
        })

    # Занятые продукты в других рационах группы
    occupied_ids = set()
    if ration.group_id:
        occupied_ids = set(
            RationSlot.objects.filter(
                ration__group_id=ration.group_id,
                product__isnull=False,
            ).exclude(ration=ration)
            .values_list("product_id", flat=True)
        )

    meal_cat_map = {}
    for key, _ in SLOT_TYPES:
        prods = list(
            Product.objects
            .filter(meal_categories__key=key)
            .exclude(pk__in=occupied_ids)
            .order_by("name")
        )
        meal_cat_map[key] = [
            {
                "id": p.pk, "name": p.name,
                "category": " / ".join(str(c) for c in p.meal_categories.all()),
                "kcal": float(p.kcal_per_serving or 0),
                "protein": float(p.protein_per_serving or 0),
                "fat": float(p.fat_per_serving or 0),
                "carbs": float(p.carbs_per_serving or 0),
                "photo": p.photo.url if p.photo else "",
            }
            for p in prods
        ]

    all_products = list(
        Product.objects
        .prefetch_related("meal_categories")
        .exclude(pk__in=occupied_ids)
        .order_by("name")
    )
    all_products_json = [
        {
            "id": p.pk, "name": p.name,
            "category": " / ".join(str(c) for c in p.meal_categories.all()),
            "kcal": float(p.kcal_per_serving or 0),
            "protein": float(p.protein_per_serving or 0),
            "fat": float(p.fat_per_serving or 0),
            "carbs": float(p.carbs_per_serving or 0),
            "photo": p.photo.url if p.photo else "",
            "meal_categories": list(p.meal_categories.values_list("key", flat=True)),
        }
        for p in all_products
    ]

    return render(request, "myapp/ration_edit.html", {
        "ration": ration,
        "slots_with_meta": slots_with_meta,
        "total_kcal": round(total_kcal, 1),
        "total_protein": round(total_protein, 1),
        "total_fat": round(total_fat, 1),
        "total_carbs": round(total_carbs, 1),
        "slot_types": SLOT_TYPES,
        "slot_icons": SLOT_ICONS,
        "slot_colors": SLOT_COLORS,
        "kcal_categories": KCAL_CATEGORIES,
        "meal_cat_map_json": json.dumps(meal_cat_map, ensure_ascii=False),
        "all_products_json": json.dumps(all_products_json, ensure_ascii=False),
        "occupied_count": len(occupied_ids),
    })


def ration_delete(request, pk):
    ration = get_object_or_404(Ration, pk=pk)
    if request.method == "POST":
        ration.delete()
    return redirect("ration_group_list")
"""
Добавь это в views.py (в конец файла).
Добавь URL в urls.py:
    path("iiko/sync/", views.iiko_sync_view, name="iiko_sync"),
"""


@require_POST
def iiko_sync_view(request):
    """
    AJAX-вьюха для синхронизации продуктов из iiko.
    Вызывается кнопкой в product_list.html.
    Возвращает JSON с результатом.
    """
    from .iiko_sync import sync_products_from_iiko

    # Настройки берём из settings.py
    cloud_api_key    = getattr(settings, "IIKO_CLOUD_API_KEY", "")
    org_id           = getattr(settings, "IIKO_ORG_ID", "")
    external_menu_id = getattr(settings, "IIKO_EXTERNAL_MENU_ID", "")
    server_url       = getattr(settings, "IIKO_SERVER_URL", "")
    server_login     = getattr(settings, "IIKO_SERVER_LOGIN", "")
    server_password  = getattr(settings, "IIKO_SERVER_PASSWORD", "")

    if not cloud_api_key or not org_id or not external_menu_id:
        return JsonResponse({
            "ok": False,
            "message": "Не заданы IIKO_CLOUD_API_KEY, IIKO_ORG_ID или IIKO_EXTERNAL_MENU_ID в settings.py"
        }, status=400)

    try:
        result = sync_products_from_iiko(
            cloud_api_key=cloud_api_key,
            org_id=org_id,
            external_menu_id=external_menu_id,
            server_url=server_url,
            server_login=server_login,
            server_password=server_password,
        )
        ok = result["skipped"] == 0 or result["created"] + result["updated"] > 0
        msg_parts = []
        if result["created"]:
            msg_parts.append(f"Создано: {result['created']}")
        if result["updated"]:
            msg_parts.append(f"Обновлено: {result['updated']}")
        if result["skipped"]:
            msg_parts.append(f"Пропущено: {result['skipped']}")
        message = " | ".join(msg_parts) if msg_parts else "Нет изменений"
        if result["errors"]:
            message += f" | Ошибок: {len(result['errors'])}"

        return JsonResponse({
            "ok": ok,
            "message": message,
            "detail": result,
        })
    except Exception as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=500)