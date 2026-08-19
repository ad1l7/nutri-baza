from decimal import Decimal, ROUND_CEILING

from django.conf import settings
from django.db import models
from django.utils import timezone

from .ingredient_aliases import clean_composition


class Allergen(models.Model):
    name = models.CharField(max_length=200, verbose_name="Аллерген")

    class Meta:
        verbose_name = "Аллерген"
        verbose_name_plural = "Аллергены"
        ordering = ["name"]

    def __str__(self):
        return self.name


SLOT_TYPES = [
    ('breakfast', 'Завтрак'),
    ('hot_400',   'Горячее 400-500'),
    ('hot_500',   'Горячее 500-600'),
    ('soup',      'Суп'),
    ('salad',     'Салат'),
    ('dessert',   'Выпечка/Десерт'),
    ('smoothie',  'Смузи'),
    ('sandwich',  'Сэндвичи'),
    ('extra',     'Доп. товары'),
]

SLOT_ORDER = {k: i for i, (k, _) in enumerate(SLOT_TYPES)}
SLOT_LABELS = dict(SLOT_TYPES)

# Категории только для каталога — НЕ участвуют в сборке рационов.
# «Доп. товары» синхронизируются и фильтруются в каталоге, но не предлагаются
# как слот при составлении рациона.
CATALOG_ONLY_KEYS = {'extra'}

# Категории, доступные в конструкторе рационов (обычный и Claude).
RATION_SLOT_TYPES = [(k, v) for k, v in SLOT_TYPES if k not in CATALOG_ONLY_KEYS]


class MealCategory(models.Model):
    key = models.CharField(
        max_length=50, unique=True, choices=SLOT_TYPES, verbose_name="Категория"
    )

    class Meta:
        verbose_name = "Категория блюда"
        verbose_name_plural = "Категории блюд"
        ordering = ["key"]

    def __str__(self):
        return SLOT_LABELS.get(self.key, self.key)


class Product(models.Model):
    name = models.CharField(max_length=300, verbose_name="Наименование")
    photo = models.ImageField(upload_to="products/", null=True, blank=True, verbose_name="Фото")
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Себестоимость ФЗ")
    # По умолчанию считается автоматически (наценка MARKUP_TARGET_PCT), но
    # введённая руками цена фиксируется флагом ниже и больше не пересчитывается.
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Цена продажи с ФЗ")
    sale_price_manual = models.BooleanField(default=False, verbose_name="Цена задана вручную")
    net_weight = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, verbose_name="Масса нетто (г)")
    packing = models.CharField(max_length=100, null=True, blank=True, verbose_name="Кратность / Фасовка")
    # composition — как пришло из техкарты iiko, храним нетронутым для сверки.
    # composition_clean — то же самое через справочник ингредиентов: без
    # артикульных хвостов и дублей. Показывается везде, пересчитывается сам.
    composition = models.TextField(null=True, blank=True, verbose_name="Состав (из iiko)")
    composition_clean = models.TextField(blank=True, default="", verbose_name="Состав")
    allergens = models.ManyToManyField(Allergen, blank=True, verbose_name="Аллергены")
    meal_categories = models.ManyToManyField(MealCategory, blank=True, verbose_name="Категории блюда")

    # КБЖУ на 100г
    protein = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Белки")
    fat = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Жиры")
    carbs = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Углеводы")
    kcal_per_100 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Ккал на 100г")
    kj_per_100 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="КДж на 100г")

    # КБЖУ на порцию
    protein_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Белки на 1 порц.")
    fat_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Жиры на 1 порц.")
    carbs_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Углеводы на 1 порц.")
    kcal_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Ккал на 1 порц.")
    kj_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="КДж на 1 порц.")

    # Артикул блюда (короткий код из iiko, для отображения)
    article = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Артикул")

    # iiko интеграция
    iiko_id = models.CharField(max_length=50, null=True, blank=True, unique=True, verbose_name="iiko UUID")
    iiko_sku = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Артикул iiko (num)")
    iiko_category = models.CharField(max_length=300, null=True, blank=True, verbose_name="Категория iiko")
    iiko_synced_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя синхронизация")

    # Ниже этой наценки себестоимость подсвечивается красным в каталоге
    MARKUP_MIN_PCT = 40
    # Целевая наценка: на неё считается цена продажи, пока её не задали руками
    MARKUP_TARGET_PCT = 67

    class Meta:
        verbose_name = "Продукт"
        verbose_name_plural = "Продукты"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Цена продажи всегда держит наценку MARKUP_TARGET_PCT — кроме блюд,
        где её задали вручную, и блюд без себестоимости (там ставить не из чего).
        Пересчёт живёт здесь, чтобы срабатывать и на синхронизации с iiko, и в
        админке — везде, где меняется себестоимость."""
        if not self.sale_price_manual:
            auto = self.auto_sale_price
            if auto is not None and auto != self.sale_price:
                self.sale_price = auto
                update_fields = kwargs.get("update_fields")
                if update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {"sale_price"}

        # Чистый состав пересчитывается из сырого — в том числе на синхронизации
        clean = clean_composition(self.composition)
        if clean != self.composition_clean:
            self.composition_clean = clean
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"composition_clean"}

        super().save(*args, **kwargs)

    # ── Наценка фудзавода (считается из cost и sale_price, в БД не хранится) ──

    @staticmethod
    def _decimal(value):
        """Приводит к Decimal. Из БД поля приходят Decimal, но синхронизация с
        iiko присваивает их как float — смешивать типы в арифметике нельзя."""
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @property
    def auto_sale_price(self):
        """Цена продажи с целевой наценкой, округлённая вверх до целых тенге.
        Округляем именно вверх — наценка не должна оказаться ниже целевой.
        None, если себестоимости нет: нулевой себес — это тоже «нет данных»."""
        if not self.cost:
            return None
        factor = Decimal(1) + Decimal(self.MARKUP_TARGET_PCT) / Decimal(100)
        return (self._decimal(self.cost) * factor).quantize(
            Decimal("1"), rounding=ROUND_CEILING)

    @property
    def markup(self):
        """Наценка в тенге: цена продажи − себестоимость.
        Считаем в Decimal — на float вылезает мусор вида 349.99999999999994."""
        if self.sale_price is None or self.cost is None:
            return None
        return self._decimal(self.sale_price) - self._decimal(self.cost)

    @property
    def markup_pct(self):
        """Наценка в процентах от себестоимости."""
        m = self.markup
        if m is None or not self.cost:
            return None
        return float(m) / float(self.cost) * 100

    @property
    def markup_is_low(self):
        """Наценка меньше нормы — повод подсветить себестоимость."""
        pct = self.markup_pct
        return pct is not None and pct < self.MARKUP_MIN_PCT


# ── Точечные права пользователя ──────────────────────────────────────────────

class UserRights(models.Model):
    """Отдельные разрешения поверх роли «читатель».

    Читатель по умолчанию не может ничего менять. Галочки здесь открывают ему
    конкретные действия — не превращая его в полноценного редактора.
    Правятся в карточке пользователя в админке."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rights", verbose_name="Пользователь",
    )
    can_edit_prices = models.BooleanField(
        default=False, verbose_name="Может менять цены продажи",
        help_text="Читатель сможет вносить «Цену прод.» в каталоге. Остальное "
                  "останется только для чтения.",
    )

    class Meta:
        verbose_name = "Права пользователя"
        verbose_name_plural = "Права пользователей"

    def __str__(self):
        return f"Права: {self.user}"


# ── Материалы (упаковка и прочее для заявочного листа) ───────────────────────

class Material(models.Model):
    """Позиция, которая не является блюдом: упаковка, вода, хладагент.
    В каталоге таких артикулов нет — они ведутся отдельно и попадают
    в конец каждого заявочного листа."""
    article = models.CharField(max_length=100, blank=True, default="", verbose_name="Артикул")
    name    = models.CharField(max_length=300, verbose_name="Наименование")
    unit    = models.CharField(max_length=50, default="1 шт", verbose_name="Кратность заказа")
    order   = models.PositiveIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Материал"
        verbose_name_plural = "Материалы"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


# ── Лог синхронизаций iiko ────────────────────────────────────────────────────

class IikoSyncLog(models.Model):
    DAILY_LIMIT = 1000  # временно увеличено для тестирования категорий

    synced_at = models.DateTimeField(auto_now_add=True, verbose_name="Время синхронизации")
    created_count = models.IntegerField(default=0, verbose_name="Создано")
    updated_count = models.IntegerField(default=0, verbose_name="Обновлено")
    deleted_count = models.IntegerField(default=0, verbose_name="Удалено")
    has_errors = models.BooleanField(default=False, verbose_name="Были ошибки")

    class Meta:
        verbose_name = "Лог синхронизации iiko"
        verbose_name_plural = "Логи синхронизаций iiko"
        ordering = ["-synced_at"]

    def __str__(self):
        return f"Синхронизация {self.synced_at.strftime('%d.%m.%Y %H:%M')}"

    @classmethod
    def used_today(cls) -> int:
        today = timezone.localdate()
        return cls.objects.filter(synced_at__date=today).count()

    @classmethod
    def remaining_today(cls) -> int:
        return max(0, cls.DAILY_LIMIT - cls.used_today())

    @classmethod
    def can_sync(cls) -> bool:
        return cls.remaining_today() > 0

    @classmethod
    def last_sync_time(cls):
        last = cls.objects.order_by("-synced_at").first()
        return last.synced_at if last else None


# ── Приёмы пищи ──────────────────────────────────────────────────────────────

class MealTime(models.Model):
    """
    Фиксированный приём пищи: Завтрак, Обед, Ужин, Перекус и т.д.
    Создаётся в админке. Используется в шаблонах рационов и слотах рациона.
    """
    name = models.CharField(max_length=100, verbose_name="Название")
    icon = models.CharField(max_length=10, blank=True, default="🍽️", verbose_name="Иконка")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Приём пищи"
        verbose_name_plural = "Приёмы пищи"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


# ── Калоражи ─────────────────────────────────────────────────────────────────
# Единый справочник категорий калорийности: целевые КБЖУ с погрешностью
# (норма = цель ± погрешность) и набор приёмов пищи. Заменил собой прежние
# RationTemplate (приёмы пищи) и RationNorm (диапазоны КБЖУ), которые
# редактировались только в админке. Теперь всё в отдельной вкладке «Калоражи».


class CalorieCategory(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название")
    kcal = models.PositiveIntegerField(unique=True, verbose_name="Калорийность, ккал")

    # Границы нормы задаются вручную «от … до …» — произвольные, не обязательно
    # симметричные относительно kcal. Имена совпадают с прежней моделью RationNorm,
    # поэтому шаблоны и проверки сборки рационов не менялись.
    kcal_min = models.PositiveIntegerField(default=0, verbose_name="Ккал — от")
    kcal_max = models.PositiveIntegerField(default=0, verbose_name="Ккал — до")
    protein_min = models.PositiveIntegerField(default=0, verbose_name="Белки — от, г")
    protein_max = models.PositiveIntegerField(default=0, verbose_name="Белки — до, г")
    fat_min = models.PositiveIntegerField(default=0, verbose_name="Жиры — от, г")
    fat_max = models.PositiveIntegerField(default=0, verbose_name="Жиры — до, г")
    carbs_min = models.PositiveIntegerField(default=0, verbose_name="Углеводы — от, г")
    carbs_max = models.PositiveIntegerField(default=0, verbose_name="Углеводы — до, г")

    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Калораж"
        verbose_name_plural = "Калоражи"
        ordering = ["order", "kcal"]

    def __str__(self):
        return self.name or f"{self.kcal} ккал"

    @property
    def kcal_category(self):
        """Ration.kcal_category хранит именно значение ккал — этот алиас
        позволяет отдавать калораж туда, где раньше ждали норму."""
        return self.kcal

    @classmethod
    def choices(cls):
        """Пары (ккал, название) для выпадающих списков выбора калоража."""
        return [(c.kcal, str(c)) for c in cls.objects.all()]

    @classmethod
    def norm_for(cls, kcal_category):
        """Калораж по числовому значению ккал рациона (или None)."""
        return cls.objects.filter(kcal=kcal_category).first()

    def meal_times(self):
        """Приёмы пищи калоража в заданном порядке."""
        return [
            m.meal_time
            for m in self.meals.select_related("meal_time").order_by("order")
            if m.meal_time_id
        ]


class CalorieCategoryMeal(models.Model):
    """Приём пищи в составе калоража: 1500 ккал → [Завтрак, Обед, Ужин]."""
    category = models.ForeignKey(
        CalorieCategory, on_delete=models.CASCADE,
        related_name="meals", verbose_name="Калораж"
    )
    meal_time = models.ForeignKey(
        MealTime, on_delete=models.CASCADE,
        related_name="calorie_meals", verbose_name="Приём пищи"
    )
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Приём пищи калоража"
        verbose_name_plural = "Приёмы пищи калоража"
        ordering = ["order", "id"]
        unique_together = [("category", "meal_time")]

    def __str__(self):
        return f"{self.category} / {self.meal_time}"



# ── Группы рационов ──────────────────────────────────────────────────────────

class RationGroup(models.Model):
    name = models.CharField(max_length=300, verbose_name="Название группы")
    description = models.TextField(null=True, blank=True, verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Группа рационов"
        verbose_name_plural = "Группы рационов"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


# ── Рационы ──────────────────────────────────────────────────────────────────

class Ration(models.Model):
    group = models.ForeignKey(
        RationGroup, on_delete=models.CASCADE,
        related_name="rations", verbose_name="Группа",
        null=True, blank=True,
    )
    name = models.CharField(max_length=300, verbose_name="Название рациона")
    # Значение ккал калоража (CalorieCategory.kcal), а не FK — чтобы удаление
    # калоража не утаскивало за собой рационы.
    kcal_category = models.IntegerField(verbose_name="Категория калорийности")
    notes = models.TextField(blank=True, null=True, verbose_name="Примечания")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Рацион"
        verbose_name_plural = "Рационы"
        ordering = ["order", "-created_at"]

    def __str__(self):
        return self.name


class RationSlot(models.Model):
    """
    Слот рациона — три уровня:
    1. meal_time  — приём пищи (Завтрак, Обед, Ужин)
    2. slot_type  — категория блюда (Суп 200 ккал, Салат 150–250 ккал)
    3. product    — конкретное блюдо
    """
    ration = models.ForeignKey(
        Ration, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Рацион"
    )
    meal_time = models.ForeignKey(
        MealTime, on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Приём пищи"
    )
    slot_type = models.CharField(
        max_length=50, choices=SLOT_TYPES,
        null=True, blank=True,
        verbose_name="Категория блюда"
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ration_slots", verbose_name="Блюдо"
    )
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Слот рациона"
        verbose_name_plural = "Слоты рациона"
        ordering = ["order", "meal_time__order"]

    def __str__(self):
        mt = self.meal_time.name if self.meal_time_id else "—"
        st = SLOT_LABELS.get(self.slot_type, self.slot_type) if self.slot_type else "без категории"
        pr = self.product.name if self.product_id else "пусто"
        return f"{mt} / {st} — {pr}"


# ── Сопоставление категорий iiko → категории сайта ───────────────────────────

class IikoCategoryMap(models.Model):
    """Соответствие названия категории/подгруппы из iiko → категория сайта.
    Позволяет гибко реагировать на изменение категорий в iiko без правки кода."""
    iiko_name = models.CharField(
        max_length=300, unique=True,
        verbose_name="Название категории в iiko"
    )
    slot_key = models.CharField(
        max_length=50, choices=SLOT_TYPES,
        verbose_name="Категория на сайте"
    )

    class Meta:
        verbose_name = "Сопоставление категории iiko"
        verbose_name_plural = "Сопоставление категорий iiko"
        ordering = ["iiko_name"]

    def __str__(self):
        return f"{self.iiko_name} → {SLOT_LABELS.get(self.slot_key, self.slot_key)}"


# ── Блюда на замену ──────────────────────────────────────────────────────────

class SwapGroup(models.Model):
    """Подгруппа блюд на замену, напр. «Завтраки на замену», «Супы на замену»."""
    name = models.CharField(max_length=300, verbose_name="Название подгруппы")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Подгруппа на замену"
        verbose_name_plural = "Блюда на замену"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class SwapItem(models.Model):
    """Позиция в подгруппе на замену — ссылка на блюдо из каталога."""
    swap_group = models.ForeignKey(
        SwapGroup, on_delete=models.CASCADE,
        related_name="items", verbose_name="Подгруппа"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name="swap_items", verbose_name="Блюдо"
    )
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Позиция на замену"
        verbose_name_plural = "Позиции на замену"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.swap_group.name} — {self.product.name}"


# ── Рационы Claude (отдельная система, изолированная от обычных рационов) ──────
# Полная копия групп/рационов/слотов, но со своим набором данных и полем wishes.
# Справочники (Product, MealTime, CalorieCategory) — общие.

class ClaudeRationGroup(models.Model):
    name = models.CharField(max_length=300, verbose_name="Название группы")
    description = models.TextField(null=True, blank=True, verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Группа рационов Claude"
        verbose_name_plural = "Группы рационов Claude"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class ClaudeRation(models.Model):
    group = models.ForeignKey(
        ClaudeRationGroup, on_delete=models.CASCADE,
        related_name="rations", verbose_name="Группа",
        null=True, blank=True,
    )
    name = models.CharField(max_length=300, verbose_name="Название рациона")
    # Значение ккал калоража (CalorieCategory.kcal), а не FK — чтобы удаление
    # калоража не утаскивало за собой рационы.
    kcal_category = models.IntegerField(verbose_name="Категория калорийности")
    wishes = models.TextField(blank=True, null=True, verbose_name="Пожелания для Claude")
    notes = models.TextField(blank=True, null=True, verbose_name="Примечания")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Рацион Claude"
        verbose_name_plural = "Рационы Claude"
        ordering = ["order", "-created_at"]

    def __str__(self):
        return self.name


class ClaudeRationSlot(models.Model):
    ration = models.ForeignKey(
        ClaudeRation, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Рацион"
    )
    meal_time = models.ForeignKey(
        MealTime, on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Приём пищи"
    )
    slot_type = models.CharField(
        max_length=50, choices=SLOT_TYPES,
        null=True, blank=True,
        verbose_name="Категория блюда"
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="claude_ration_slots", verbose_name="Блюдо"
    )
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Слот рациона Claude"
        verbose_name_plural = "Слоты рационов Claude"
        ordering = ["order", "meal_time__order"]

    def __str__(self):
        mt = self.meal_time.name if self.meal_time_id else "—"
        pr = self.product.name if self.product_id else "пусто"
        return f"{mt} — {pr}"