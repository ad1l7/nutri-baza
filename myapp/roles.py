"""Роль «читатель» — пользователь только смотрит, ничего не меняет.

Читатель = залогинен, НЕ суперюзер и состоит в группе READERS_GROUP.
Существующие пользователи (вне группы) остаются полноправными — добавление
роли никого не понижает.
"""

READERS_GROUP = "readers"


def is_reader(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and not user.is_superuser
        and user.groups.filter(name=READERS_GROUP).exists()
    )
