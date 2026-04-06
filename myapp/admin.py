from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "kcal_per_100", "protein", "fat", "carbs", "packing"]
    list_filter = ["category", "packing"]
    search_fields = ["name", "composition"]
    ordering = ["category", "name"]