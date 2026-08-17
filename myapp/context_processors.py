from .roles import can_edit_prices, is_reader


def user_role(request):
    """Флаги роли для шаблонов: is_reader прячет кнопки создания/правки/
    удаления/синхронизации, can_edit_prices открывает поле цены в каталоге
    даже читателю — если ему это разрешили персонально."""
    user = getattr(request, "user", None)
    return {
        "is_reader": is_reader(user),
        "can_edit_prices": can_edit_prices(user),
    }
