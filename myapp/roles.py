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


def can_manage_claude_rations(user) -> bool:
    """Кому вкладка «Рационы Claude» доступна на запись.

    Полноправные редакторы — как и раньше. Читателю право открывается галочкой
    «Может вести рационы Claude» в его карточке в админке; что именно ему можно
    править, решают can_edit_claude_group / can_edit_claude_ration."""
    if not (user and user.is_authenticated):
        return False
    if not is_reader(user):
        return True
    rights = getattr(user, "rights", None)
    return bool(rights and rights.can_edit_claude_rations)


def is_limited_claude_editor(user) -> bool:
    """Читатель с правом вести рационы Claude: правит только своё и группы,
    отмеченные как открытые. Полноправный редактор сюда не попадает."""
    return is_reader(user) and can_manage_claude_rations(user)


def can_edit_claude_group(user, group) -> bool:
    """Группа рационов Claude: правка, удаление, создание рационов внутри."""
    if not can_manage_claude_rations(user):
        return False
    if not is_limited_claude_editor(user):
        return True
    if group is None:
        return False
    return bool(group.shared_editing or group.created_by_id == user.id)


def can_edit_claude_ration(user, ration) -> bool:
    """Рацион Claude: свой — всегда; чужой — только внутри доступной группы.

    Рационы, созданные ограниченным редактором, остаются доступны обычным
    редакторам: у них проверка заканчивается на can_manage_claude_rations."""
    if not can_manage_claude_rations(user):
        return False
    if not is_limited_claude_editor(user):
        return True
    if ration is None:
        return False
    if ration.created_by_id == user.id:
        return True
    return can_edit_claude_group(user, ration.group)


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
