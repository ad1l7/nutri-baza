from django.urls import path
from . import views

urlpatterns = [
    # Каталог
    path("", views.product_list, name="product_list"),
    path("product/<int:pk>/", views.product_detail, name="product_detail"),

    # Рационы
    path("rations/", views.ration_list, name="ration_list"),
    path("rations/create/", views.ration_create, name="ration_create"),
    path("rations/<int:pk>/edit/", views.ration_edit, name="ration_edit"),
    path("rations/<int:pk>/delete/", views.ration_delete, name="ration_delete"),
]