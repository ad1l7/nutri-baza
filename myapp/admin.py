from django.contrib import admin
from .models import (
    IikoSyncLog,
    Product, Allergen, MealCategory, MealTime,
    RationGroup, Ration, RationSlot,
    RationTemplate, RationTemplateSlot,
    RationNorm, IikoCategoryMap,
    SwapGroup, SwapItem,
    ClaudeRationGroup, ClaudeRation, ClaudeRationSlot,
    KCAL_CATEGORIES,
)


@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(MealCategory)
class MealCategoryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "key"]


@admin.register(MealTime)
class MealTimeAdmin(admin.ModelAdmin):
    list_display = ["order", "icon", "name"]
    list_editable = ["icon", "name"]
    ordering = ["order"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "article", "get_categories", "cost", "kcal_per_100", "protein", "fat", "carbs", "packing"]
    list_filter = ["meal_categories", "packing", "allergens"]
    search_fields = ["name", "article", "composition"]
    ordering = ["name"]
    filter_horizontal = ["allergens", "meal_categories"]
    fieldsets = [
        ("Основное", {
            "fields": ["name", "article", "photo", "cost", "packing", "net_weight", "composition", "allergens", "meal_categories"]
        }),
        ("На 100 г", {
            "fields": ["protein", "fat", "carbs", "kcal_per_100", "kj_per_100"]
        }),
        ("На 1 порцию", {
            "fields": ["protein_per_serving", "fat_per_serving", "carbs_per_serving", "kcal_per_serving", "kj_per_serving"]
        }),
        ("iiko", {
            "fields": ["iiko_id", "iiko_sku", "iiko_category", "iiko_synced_at"],
            "classes": ["collapse"],
        }),
    ]

    def get_categories(self, obj):
        return ", ".join(str(c) for c in obj.meal_categories.all()) or "—"
    get_categories.short_description = "Категории"


# ── Шаблоны рационов ─────────────────────────────────────────────────────────

class RationTemplateSlotInline(admin.TabularInline):
    model = RationTemplateSlot
    extra = 1
    fields = ["order", "meal_time"]  # meal_time вместо slot_type
    ordering = ["order"]


@admin.register(RationTemplate)
class RationTemplateAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kcal_category", "get_slots_count", "updated_at"]
    inlines = [RationTemplateSlotInline]
    readonly_fields = ["updated_at"]

    def get_slots_count(self, obj):
        return obj.slots.count()
    get_slots_count.short_description = "Приёмов пищи"

    def has_add_permission(self, request):
        existing = RationTemplate.objects.count()
        return existing < len(KCAL_CATEGORIES)


# ── Группы и рационы ─────────────────────────────────────────────────────────

class RationInline(admin.TabularInline):
    model = Ration
    extra = 0
    fields = ["name", "kcal_category"]
    show_change_link = True


@admin.register(RationGroup)
class RationGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "get_rations_count", "created_at"]
    search_fields = ["name"]
    inlines = [RationInline]

    def get_rations_count(self, obj):
        return obj.rations.count()
    get_rations_count.short_description = "Рационов"


class RationSlotInline(admin.TabularInline):
    model = RationSlot
    extra = 0
    fields = ["meal_time", "slot_type", "product", "order"]


@admin.register(Ration)
class RationAdmin(admin.ModelAdmin):
    list_display = ["name", "group", "kcal_category"]
    list_filter = ["group", "kcal_category"]
    search_fields = ["name"]
    inlines = [RationSlotInline]


# ── Нормы КБЖУ ───────────────────────────────────────────────────────────────

@admin.register(RationNorm)
class RationNormAdmin(admin.ModelAdmin):
    list_display = [
        "kcal_category", "kcal_min", "kcal_max",
        "protein_min", "protein_max", "fat_min", "fat_max",
        "carbs_min", "carbs_max",
    ]
    list_editable = [
        "kcal_min", "kcal_max", "protein_min", "protein_max",
        "fat_min", "fat_max", "carbs_min", "carbs_max",
    ]


@admin.register(IikoCategoryMap)
class IikoCategoryMapAdmin(admin.ModelAdmin):
    list_display = ["iiko_name", "slot_key"]
    list_editable = ["slot_key"]
    search_fields = ["iiko_name"]
    list_filter = ["slot_key"]


# ── Блюда на замену ──────────────────────────────────────────────────────────

class SwapItemInline(admin.TabularInline):
    model = SwapItem
    extra = 1
    fields = ["product", "order"]
    autocomplete_fields = ["product"]


@admin.register(SwapGroup)
class SwapGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "get_items_count", "order"]
    search_fields = ["name"]
    inlines = [SwapItemInline]

    def get_items_count(self, obj):
        return obj.items.count()
    get_items_count.short_description = "Позиций"


# ── Рационы Claude ───────────────────────────────────────────────────────────

class ClaudeRationInline(admin.TabularInline):
    model = ClaudeRation
    extra = 0
    fields = ["name", "kcal_category"]
    show_change_link = True


@admin.register(ClaudeRationGroup)
class ClaudeRationGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "get_rations_count", "created_at"]
    search_fields = ["name"]
    inlines = [ClaudeRationInline]

    def get_rations_count(self, obj):
        return obj.rations.count()
    get_rations_count.short_description = "Рационов"


class ClaudeRationSlotInline(admin.TabularInline):
    model = ClaudeRationSlot
    extra = 0
    fields = ["meal_time", "slot_type", "product", "order"]


@admin.register(ClaudeRation)
class ClaudeRationAdmin(admin.ModelAdmin):
    list_display = ["name", "group", "kcal_category"]
    list_filter = ["group", "kcal_category"]
    search_fields = ["name"]
    inlines = [ClaudeRationSlotInline]


# ── iiko Лог ─────────────────────────────────────────────────────────────────

@admin.register(IikoSyncLog)
class IikoSyncLogAdmin(admin.ModelAdmin):
    list_display = ["synced_at", "created_count", "updated_count", "deleted_count", "has_errors"]
    readonly_fields = ["synced_at", "created_count", "updated_count", "deleted_count", "has_errors"]
    ordering = ["-synced_at"]
    actions = ["reset_daily_limit"]

    @admin.action(description="🔄 Сбросить лимит синхронизаций сегодня")
    def reset_daily_limit(self, request, queryset):
        from django.utils import timezone
        today = timezone.localdate()
        deleted, _ = IikoSyncLog.objects.filter(synced_at__date=today).delete()
        self.message_user(
            request,
            f"✅ Лимит сброшен — удалено {deleted} записей за сегодня. "
            f"Теперь доступно {IikoSyncLog.DAILY_LIMIT} синхронизаций.",
        )