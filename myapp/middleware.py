import re

from django.shortcuts import redirect
from django.conf import settings
from django.http import HttpResponseForbidden

from .roles import can_edit_prices, is_reader


class ReaderReadOnlyMiddleware:
    """Роль «читатель» может только смотреть: любой изменяющий запрос
    (POST/PUT/PATCH/DELETE) блокируется, кроме входа и выхода. Это защита
    на бэкенде — даже если кнопку не спрятали или читатель отправит запрос
    напрямую, изменение не пройдёт.

    Исключение — сохранение цены продажи: оно открывается персонально
    галочкой «Может менять цены продажи» в карточке пользователя."""

    ALLOWED_PATHS = ("/login/", "/logout/")
    SALE_PRICE_PATH = re.compile(r"^/product/\d+/sale-price/$")
    UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method in self.UNSAFE_METHODS
            and request.path_info not in self.ALLOWED_PATHS
            and is_reader(request.user)
        ):
            price_request = self.SALE_PRICE_PATH.match(request.path_info)
            if not (price_request and can_edit_prices(request.user)):
                return HttpResponseForbidden(
                    "Доступ только для чтения: у вашей роли нет прав на изменение."
                )
        return self.get_response(request)


class LoginRequiredMiddleware:
    """
    Перенаправляет неавторизованных пользователей на страницу логина.
    Исключения: сама страница /login/ и /admin/.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        login_url = getattr(settings, "LOGIN_URL", "/login/")
        path = request.path_info

        # Пропускаем: страница входа и Django-админка
        if not request.user.is_authenticated:
            if not (path == login_url or path.startswith("/admin/")):
                next_url = path
                return redirect(f"{login_url}?next={next_url}")

        return self.get_response(request)
