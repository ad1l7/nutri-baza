from django.shortcuts import redirect
from django.conf import settings


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
