from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
import json

from .models import Product, Allergen, Ration, RationSlot, SLOT_TYPES, SLOT_ORDER


# ── Каталог продуктов ─────────────────────────────────────────────────────────

def product_list(request):
    products = Product.objects.all()
    categories = Product.objects.values_list("category", flat=True).distinct().order_by("category")
    all_allergens = Allergen.objects.all()

    search              = request.GET.get("search", "").strip()
    selected_categories = request.GET.getlist("category")
    selected_allergens  = request.GET.getlist("allergen")
    cost_min = request.GET.get("cost_min", "")
    cost_max = request.GET.get("cost_max", "")
    kcal_min    = request.GET.get("kcal_min", "")
    kcal_max    = request.GET.get("kcal_max", "")
    protein_min = request.GET.get("protein_min", "")
    protein_max = request.GET.get("protein_max", "")
    fat_min     = request.GET.get("fat_min", "")
    fat_max     = request.GET.get("fat_max", "")
    carbs_min   = request.GET.get("carbs_min", "")
    carbs_max   = request.GET.get("carbs_max", "")
    kcal_s_min    = request.GET.get("kcal_s_min", "")
    kcal_s_max    = request.GET.get("kcal_s_max", "")
    protein_s_min = request.GET.get("protein_s_min", "")
    protein_s_max = request.GET.get("protein_s_max", "")
    fat_s_min     = request.GET.get("fat_s_min", "")
    fat_s_max     = request.GET.get("fat_s_max", "")
    carbs_s_min   = request.GET.get("carbs_s_min", "")
    carbs_s_max   = request.GET.get("carbs_s_max", "")
    packing  = request.GET.get("packing", "").strip()
    sort_by  = request.GET.get("sort", "name")
    sort_dir = request.GET.get("dir", "asc")

    if search:
        products = products.filter(Q(name__icontains=search) | Q(composition__icontains=search))
    if selected_categories:
        products = products.filter(category__in=selected_categories)
    if selected_allergens:
        products = products.filter(allergens__pk__in=selected_allergens).distinct()
    if cost_min: products = products.filter(cost__gte=cost_min)
    if cost_max: products = products.filter(cost__lte=cost_max)
    if kcal_min:    products = products.filter(kcal_per_100__gte=kcal_min)
    if kcal_max:    products = products.filter(kcal_per_100__lte=kcal_max)
    if protein_min: products = products.filter(protein__gte=protein_min)
    if protein_max: products = products.filter(protein__lte=protein_max)
    if fat_min:     products = products.filter(fat__gte=fat_min)
    if fat_max:     products = products.filter(fat__lte=fat_max)
    if carbs_min:   products = products.filter(carbs__gte=carbs_min)
    if carbs_max:   products = products.filter(carbs__lte=carbs_max)
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
        "name": "name", "category": "category",
        "net_weight": "net_weight", "cost": "cost",
        "kcal": "kcal_per_100", "protein": "protein",
        "fat": "fat", "carbs": "carbs",
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
        "categories": categories, "packings": packings,
        "all_allergens": all_allergens,
        "selected_categories": selected_categories,
        "selected_allergens": selected_allergens,
        "selected_allergen_names": selected_allergen_names,
        "filters": {
            "search": search,
            "cost_min": cost_min, "cost_max": cost_max,
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


# ── Рационы ───────────────────────────────────────────────────────────────────

SLOT_LABELS = dict(SLOT_TYPES)

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


def ration_list(request):
    rations = Ration.objects.prefetch_related("slots__product").all()
    kcal_filter = request.GET.get("kcal", "")
    search = request.GET.get("search", "").strip()
    if kcal_filter:
        rations = rations.filter(kcal_category=kcal_filter)
    if search:
        rations = rations.filter(name__icontains=search)

    rations_data = []
    for r in rations:
        slots = list(r.slots.select_related("product").all())
        total_kcal    = sum(float(s.product.kcal_per_serving or 0) for s in slots if s.product)
        total_protein = sum(float(s.product.protein_per_serving or 0) for s in slots if s.product)
        total_fat     = sum(float(s.product.fat_per_serving or 0) for s in slots if s.product)
        total_carbs   = sum(float(s.product.carbs_per_serving or 0) for s in slots if s.product)
        rations_data.append({
            "ration": r,
            "slots": slots,
            "total_kcal": round(total_kcal, 1),
            "total_protein": round(total_protein, 1),
            "total_fat": round(total_fat, 1),
            "total_carbs": round(total_carbs, 1),
            "slots_count": len(slots),
            "filled_count": sum(1 for s in slots if s.product),
        })

    return render(request, "myapp/ration_list.html", {
        "rations_data": rations_data,
        "kcal_categories": Ration._meta.get_field("kcal_category").choices,
        "kcal_filter": kcal_filter,
        "search": search,
        "slot_icons": SLOT_ICONS,
        "slot_colors": SLOT_COLORS,
    })


def ration_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        date = request.POST.get("date", "")
        kcal_category = request.POST.get("kcal_category", "")
        notes = request.POST.get("notes", "").strip()
        if name and date and kcal_category:
            ration = Ration.objects.create(
                name=name, date=date,
                kcal_category=int(kcal_category),
                notes=notes or None,
            )
            return redirect("ration_edit", pk=ration.pk)
    return redirect("ration_list")


def ration_edit(request, pk):
    ration = get_object_or_404(Ration, pk=pk)
    all_products = Product.objects.order_by("category", "name")

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "update_meta":
            ration.name = request.POST.get("name", ration.name).strip()
            ration.date = request.POST.get("date", str(ration.date))
            ration.kcal_category = int(request.POST.get("kcal_category", ration.kcal_category))
            ration.notes = request.POST.get("notes", "").strip() or None
            ration.save()

        elif action == "add_slot":
            slot_type = request.POST.get("slot_type", "")
            product_id = request.POST.get("product_id", "") or None
            if slot_type:
                RationSlot.objects.create(
                    ration=ration, slot_type=slot_type,
                    product_id=product_id,
                    order=SLOT_ORDER.get(slot_type, 99),
                )

        elif action == "update_slot":
            slot_id = request.POST.get("slot_id")
            product_id = request.POST.get("product_id") or None
            try:
                slot = RationSlot.objects.get(pk=slot_id, ration=ration)
                slot.product_id = product_id
                slot.save()
            except RationSlot.DoesNotExist:
                pass

        elif action == "delete_slot":
            slot_id = request.POST.get("slot_id")
            RationSlot.objects.filter(pk=slot_id, ration=ration).delete()

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
        total_kcal += kcal; total_protein += protein
        total_fat  += fat;  total_carbs   += carbs
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

    products_by_category = {}
    for p in all_products:
        products_by_category.setdefault(p.category, []).append(p)

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
        "products_by_category": products_by_category,
        "kcal_categories": Ration._meta.get_field("kcal_category").choices,
        "all_products_json": json.dumps([
            {
                "id": p.pk, "name": p.name, "category": p.category,
                "kcal": float(p.kcal_per_serving or 0),
                "protein": float(p.protein_per_serving or 0),
                "fat": float(p.fat_per_serving or 0),
                "carbs": float(p.carbs_per_serving or 0),
                "photo": p.photo.url if p.photo else "",
            }
            for p in all_products
        ], ensure_ascii=False),
    })


def ration_delete(request, pk):
    ration = get_object_or_404(Ration, pk=pk)
    if request.method == "POST":
        ration.delete()
    return redirect("ration_list")