from django.contrib import admin
from .models import Product, Allergen


@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "cost", "kcal_per_100", "protein", "fat", "carbs", "packing"]
    list_filter = ["category", "packing", "allergens"]
    search_fields = ["name", "composition"]
    ordering = ["category", "name"]
    filter_horizontal = ["allergens"]
    fieldsets = [
        ("Основное", {
            "fields": ["category", "name", "photo", "cost", "packing", "net_weight", "composition", "allergens"]
        }),
        ("На 100 г", {
            "fields": ["protein", "fat", "carbs", "kcal_per_100", "kj_per_100"]
        }),
        ("На 1 порцию", {
            "fields": ["protein_per_serving", "fat_per_serving", "carbs_per_serving", "kcal_per_serving", "kj_per_serving"]
        }),
    ]