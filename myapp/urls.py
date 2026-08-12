from django.urls import path
from . import views

urlpatterns = [
    # Каталог
    path("", views.product_list, name="product_list"),
    path("export/", views.product_export, name="product_export"),
    path("product/<int:pk>/", views.product_detail, name="product_detail"),
    path("product/<int:pk>/sale-price/", views.product_set_sale_price, name="product_set_sale_price"),

    # Калоражи (только для редакторов)
    path("calories/", views.calorie_list, name="calorie_list"),
    path("calories/create/", views.calorie_create, name="calorie_create"),
    path("calories/<int:pk>/edit/", views.calorie_edit, name="calorie_edit"),
    path("calories/<int:pk>/delete/", views.calorie_delete, name="calorie_delete"),

    # Рационы Claude (отдельная система групп/рационов + сборка Claude)
    path("claude/", views.claude_group_list, name="claude_rations"),
    path("claude/order-sheet/", views.claude_order_sheet, name="claude_order_sheet"),
    path("claude/rations/reorder/", views.claude_ration_reorder, name="claude_ration_reorder"),
    path("claude/group/create/", views.claude_group_create, name="claude_group_create"),
    path("claude/group/<int:group_pk>/edit/", views.claude_group_edit, name="claude_group_edit"),
    path("claude/group/<int:group_pk>/delete/", views.claude_group_delete, name="claude_group_delete"),
    path("claude/group/<int:group_pk>/detail/", views.claude_group_detail, name="claude_group_detail"),
    path("claude/group/<int:group_pk>/export/", views.claude_group_export, name="claude_group_export"),
    path("claude/group/<int:group_pk>/create-ration/", views.claude_ration_create, name="claude_ration_create"),
    path("claude/ration/<int:pk>/edit/", views.claude_ration_edit, name="claude_ration_edit"),
    path("claude/ration/<int:pk>/delete/", views.claude_ration_delete, name="claude_ration_delete"),

    # Блюда на замену
    path("swap/", views.swap_list, name="swap_list"),
    path("swap/group/create/", views.swap_group_create, name="swap_group_create"),
    path("swap/group/<int:group_pk>/edit/", views.swap_group_edit, name="swap_group_edit"),
    path("swap/group/<int:group_pk>/delete/", views.swap_group_delete, name="swap_group_delete"),
    path("swap/group/<int:group_pk>/export/", views.swap_group_export, name="swap_group_export"),
    path("swap/group/<int:group_pk>/add/", views.swap_item_add, name="swap_item_add"),
    path("swap/item/<int:item_pk>/remove/", views.swap_item_remove, name="swap_item_remove"),

    # iiko
    path("iiko/sync/", views.iiko_sync_view, name="iiko_sync"),
    path("iiko/status/", views.iiko_sync_status, name="iiko_sync_status"),
]