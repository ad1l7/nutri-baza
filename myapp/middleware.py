from django.shortcuts import redirect
from django.conf import settings
from django.http import HttpResponseForbidden

from .roles import is_reader


class ReaderReadOnlyMiddleware:
    """Роль «читатель» может только смотреть: любой изменяющий запрос
    (POST/PUT/PATCH/DELETE) блокируется, кроме входа и выхода. Это защита
    на бэкенде — даже если кнопку не спрятали или читатель отправит запрос
    напрямую, изменение не пройдёт."""

    ALLOWED_PATHS = ("/login/", "/logout/")
    UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method in self.UNSAFE_METHODS
            and request.path_info not in self.ALLOWED_PATHS
            and is_reader(request.user)
        ):
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
