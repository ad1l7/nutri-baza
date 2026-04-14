from django.urls import path
from . import views

urlpatterns = [
    # Каталог
    path("", views.product_list, name="product_list"),
    path("product/<int:pk>/", views.product_detail, name="product_detail"),
    # Группы рационов
    path("rations/", views.ration_group_list, name="ration_group_list"),
    path("rations/group/create/", views.ration_group_create, name="ration_group_create"),
    path("rations/group/<int:group_pk>/delete/", views.ration_group_delete, name="ration_group_delete"),
    path("rations/group/<int:group_pk>/", views.ration_list, name="ration_list"),
    path("rations/group/<int:group_pk>/create/", views.ration_create, name="ration_create"),

    # Рационы
    path("rations/<int:pk>/edit/", views.ration_edit, name="ration_edit"),
    path("rations/<int:pk>/delete/", views.ration_delete, name="ration_delete"),
    path("iiko/sync/", views.iiko_sync_view, name="iiko_sync"),
]