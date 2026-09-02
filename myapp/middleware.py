import re

from django.shortcuts import redirect
from django.conf import settings
from django.http import HttpResponseForbidden

from .roles import can_edit_prices, can_manage_claude_rations, is_reader


class ReaderReadOnlyMiddleware:
    """Роль «читатель» может только смотреть: любой изменяющий запрос
    (POST/PUT/PATCH/DELETE) блокируется, кроме входа и выхода. Это защита
    на бэкенде — даже если кнопку не спрятали или читатель отправит запрос
    напрямую, изменение не пройдёт.

    Исключения открываются персонально галочками в карточке пользователя:
    «Может менять цены продажи» — сохранение цены в каталоге, «Может вести
    рационы Claude» — вкладка рационов Claude. Во втором случае middleware
    только пропускает запрос дальше: доступ к конкретной группе или рациону
    проверяют сами вьюхи (roles.can_edit_claude_group / can_edit_claude_ration),
    иначе читатель правил бы чужие рационы."""

    ALLOWED_PATHS = ("/login/", "/logout/")
    SALE_PRICE_PATH = re.compile(r"^/product/\d+/sale-price/$")
    CLAUDE_PATH = re.compile(r"^/claude/")
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
            claude_request = self.CLAUDE_PATH.match(request.path_info)
            allowed = (
                (price_request and can_edit_prices(request.user))
                or (claude_request and can_manage_claude_rations(request.user))
            )
            if not allowed:
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
