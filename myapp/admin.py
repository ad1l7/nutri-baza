from django.contrib import admin
from .models import (
    IikoSyncLog,
    Product, Allergen, MealCategory, MealTime,
    RationGroup, Ration, RationSlot,
    RationTemplate, RationTemplateSlot,
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
    list_display = ["name", "get_categories", "cost", "kcal_per_100", "protein", "fat", "carbs", "packing"]
    list_filter = ["meal_categories", "packing", "allergens"]
    search_fields = ["name", "composition"]
    ordering = ["name"]
    filter_horizontal = ["allergens", "meal_categories"]
    fieldsets = [
        ("Основное", {
            "fields": ["name", "photo", "cost", "packing", "net_weight", "composition", "allergens", "meal_categories"]
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