"""Роль «читатель» — пользователь только смотрит, ничего не меняет.

Читатель = залогинен, НЕ суперюзер и состоит в группе READERS_GROUP.
Существующие пользователи (вне группы) остаются полноправными — добавление
роли никого не понижает.
"""

from functools import wraps

from django.http import HttpResponseForbidden

READERS_GROUP = "readers"


def is_reader(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and not user.is_superuser
        and user.groups.filter(name=READERS_GROUP).exists()
    )


def can_edit_prices(user) -> bool:
    """Кто может вносить «Цену прод.» в каталоге.

    Все, кроме читателей, — как и раньше. Читателю право открывается
    галочкой «Может менять цены продажи» в его карточке в админке."""
    if not (user and user.is_authenticated):
        return False
    if not is_reader(user):
        return True
    rights = getattr(user, "rights", None)
    return bool(rights and rights.can_edit_prices)


def editor_required(view):
    """Страница целиком недоступна читателю — даже на просмотр.

    ReaderReadOnlyMiddleware режет только изменяющие запросы; этот декоратор
    закрывает и GET, чтобы вкладку нельзя было открыть по прямой ссылке."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if is_reader(getattr(request, "user", None)):
            return HttpResponseForbidden(
                "Раздел доступен только редакторам."
            )
        return view(request, *args, **kwargs)
    return _wrapped
