from .roles import is_reader


def user_role(request):
    """Делает флаг is_reader доступным во всех шаблонах — чтобы прятать
    кнопки создания/правки/удаления/синхронизации у роли «читатель»."""
    return {"is_reader": is_reader(getattr(request, "user", None))}
