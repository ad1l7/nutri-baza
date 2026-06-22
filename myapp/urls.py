from django.urls import path
from . import views

urlpatterns = [
    # Каталог
    path("", views.product_list, name="product_list"),
    path("product/<int:pk>/", views.product_detail, name="product_detail"),

    # Группы рационов
    path("rations/", views.ration_group_list, name="ration_group_list"),
    path("rations/group/create/", views.ration_group_create, name="ration_group_create"),
    path("rations/reorder/", views.ration_reorder, name="ration_reorder"),
    path("rations/group/<int:group_pk>/edit/", views.ration_group_edit, name="ration_group_edit"),
    path("rations/group/<int:group_pk>/delete/", views.ration_group_delete, name="ration_group_delete"),
    path("rations/group/<int:group_pk>/", views.ration_list, name="ration_list"),
    path("rations/group/<int:group_pk>/create/", views.ration_create, name="ration_create"),
    path("rations/group/<int:group_pk>/detail/", views.ration_group_detail, name="ration_group_detail"),
    path("rations/group/<int:group_pk>/export/", views.ration_group_export, name="ration_group_export"),

    # Рационы
    path("rations/<int:pk>/edit/", views.ration_edit, name="ration_edit"),
    path("rations/<int:pk>/delete/", views.ration_delete, name="ration_delete"),

    # Блюда на замену
    path("swap/", views.swap_list, name="swap_list"),
    path("swap/group/create/", views.swap_group_create, name="swap_group_create"),
    path("swap/group/<int:group_pk>/edit/", views.swap_group_edit, name="swap_group_edit"),
    path("swap/group/<int:group_pk>/delete/", views.swap_group_delete, name="swap_group_delete"),
    path("swap/group/<int:group_pk>/add/", views.swap_item_add, name="swap_item_add"),
    path("swap/item/<int:item_pk>/remove/", views.swap_item_remove, name="swap_item_remove"),

    # iiko
    path("iiko/sync/", views.iiko_sync_view, name="iiko_sync"),
    path("iiko/status/", views.iiko_sync_status, name="iiko_sync_status"),
]