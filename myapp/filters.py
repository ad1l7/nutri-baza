# filters.py
import django_filters
from .models import Product

class ProductFilter(django_filters.FilterSet):
    kcal_100_min = django_filters.NumberFilter(field_name="kcal_100", lookup_expr='gte')
    kcal_100_max = django_filters.NumberFilter(field_name="kcal_100", lookup_expr='lte')

    category = django_filters.CharFilter(lookup_expr='icontains')
    name = django_filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = Product
        fields = ['category', 'name']