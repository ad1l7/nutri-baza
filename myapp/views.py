from django.shortcuts import render
from django.db.models import Q, Min, Max
from .models import Product


def product_list(request):
    products = Product.objects.all()

    # --- Categories ---
    categories = Product.objects.values_list("category", flat=True).distinct().order_by("category")

    # --- Apply filters ---
    search = request.GET.get("search", "").strip()
    selected_categories = request.GET.getlist("category")

    # На 100г
    kcal_min        = request.GET.get("kcal_min", "")
    kcal_max        = request.GET.get("kcal_max", "")
    protein_min     = request.GET.get("protein_min", "")
    protein_max     = request.GET.get("protein_max", "")
    fat_min         = request.GET.get("fat_min", "")
    fat_max         = request.GET.get("fat_max", "")
    carbs_min       = request.GET.get("carbs_min", "")
    carbs_max       = request.GET.get("carbs_max", "")

    # На 1 порцию
    kcal_s_min      = request.GET.get("kcal_s_min", "")
    kcal_s_max      = request.GET.get("kcal_s_max", "")
    protein_s_min   = request.GET.get("protein_s_min", "")
    protein_s_max   = request.GET.get("protein_s_max", "")
    fat_s_min       = request.GET.get("fat_s_min", "")
    fat_s_max       = request.GET.get("fat_s_max", "")
    carbs_s_min     = request.GET.get("carbs_s_min", "")
    carbs_s_max     = request.GET.get("carbs_s_max", "")

    packing  = request.GET.get("packing", "").strip()
    sort_by  = request.GET.get("sort", "name")
    sort_dir = request.GET.get("dir", "asc")

    if search:
        products = products.filter(
            Q(name__icontains=search) | Q(composition__icontains=search)
        )

    if selected_categories:
        products = products.filter(category__in=selected_categories)

    # Фильтры на 100г
    if kcal_min:    products = products.filter(kcal_per_100__gte=kcal_min)
    if kcal_max:    products = products.filter(kcal_per_100__lte=kcal_max)
    if protein_min: products = products.filter(protein__gte=protein_min)
    if protein_max: products = products.filter(protein__lte=protein_max)
    if fat_min:     products = products.filter(fat__gte=fat_min)
    if fat_max:     products = products.filter(fat__lte=fat_max)
    if carbs_min:   products = products.filter(carbs__gte=carbs_min)
    if carbs_max:   products = products.filter(carbs__lte=carbs_max)

    # Фильтры на порцию
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

    # --- Sorting ---
    sort_map = {
        "name":       "name",
        "category":   "category",
        "kcal":       "kcal_per_100",
        "protein":    "protein",
        "fat":        "fat",
        "carbs":      "carbs",
        "net_weight": "net_weight",
        "kcal_s":     "kcal_per_serving",
        "protein_s":  "protein_per_serving",
        "fat_s":      "fat_per_serving",
        "carbs_s":    "carbs_per_serving",
    }
    sort_field = sort_map.get(sort_by, "name")
    if sort_dir == "desc":
        sort_field = f"-{sort_field}"
    products = products.order_by(sort_field)

    total = products.count()

    packings = (
        Product.objects.values_list("packing", flat=True)
        .distinct()
        .exclude(packing__isnull=True)
        .exclude(packing="")
        .order_by("packing")
    )

    context = {
        "products": products,
        "total": total,
        "categories": categories,
        "packings": packings,
        "selected_categories": selected_categories,
        "filters": {
            "search": search,
            "kcal_min": kcal_min, "kcal_max": kcal_max,
            "protein_min": protein_min, "protein_max": protein_max,
            "fat_min": fat_min, "fat_max": fat_max,
            "carbs_min": carbs_min, "carbs_max": carbs_max,
            "kcal_s_min": kcal_s_min, "kcal_s_max": kcal_s_max,
            "protein_s_min": protein_s_min, "protein_s_max": protein_s_max,
            "fat_s_min": fat_s_min, "fat_s_max": fat_s_max,
            "carbs_s_min": carbs_s_min, "carbs_s_max": carbs_s_max,
            "packing": packing,
            "sort": sort_by,
            "dir": sort_dir,
        },
    }
    return render(request, "myapp/product_list.html", context)


def product_detail(request, pk):
    from django.shortcuts import get_object_or_404
    product = get_object_or_404(Product, pk=pk)
    return render(request, "myapp/product_detail.html", {"product": product})