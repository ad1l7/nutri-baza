from django.db import models
from django.utils import timezone


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
]

SLOT_ORDER = {k: i for i, (k, _) in enumerate(SLOT_TYPES)}
SLOT_LABELS = dict(SLOT_TYPES)


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
    net_weight = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, verbose_name="Масса нетто (г)")
    packing = models.CharField(max_length=100, null=True, blank=True, verbose_name="Кратность / Фасовка")
    composition = models.TextField(null=True, blank=True, verbose_name="Состав")
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

    class Meta:
        verbose_name = "Продукт"
        verbose_name_plural = "Продукты"
        ordering = ["name"]

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


# ── Шаблоны рационов ─────────────────────────────────────────────────────────

KCAL_CATEGORIES = [
    (1200, '1200 ккал'),
    (1500, '1500 ккал'),
    (1800, '1800 ккал'),
    (2500, '2500 ккал'),
]


class RationTemplate(models.Model):
    kcal_category = models.IntegerField(
        choices=KCAL_CATEGORIES, unique=True,
        verbose_name="Категория калорийности"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Шаблон рациона"
        verbose_name_plural = "Шаблоны рационов"
        ordering = ["kcal_category"]

    def __str__(self):
        return f"Шаблон {self.kcal_category} ккал"


class RationTemplateSlot(models.Model):
    """
    Слот шаблона — привязывает приём пищи (MealTime) к шаблону рациона.
    Например: Шаблон 1200 ккал → [Завтрак, Обед, Ужин]
    """
    template = models.ForeignKey(
        RationTemplate, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Шаблон"
    )
    meal_time = models.ForeignKey(
        MealTime, on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Приём пищи"
    )
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Слот шаблона"
        verbose_name_plural = "Слоты шаблона"
        ordering = ["order"]

    def __str__(self):
        return f"{self.template} / {self.meal_time}"


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
    kcal_category = models.IntegerField(choices=KCAL_CATEGORIES, verbose_name="Категория калорийности")
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


# ── Нормы КБЖУ по калорийности ───────────────────────────────────────────────

class RationNorm(models.Model):
    """Допустимые диапазоны КБЖУ для каждой категории калорийности.
    Редактируется в админке. Используется на сборке рациона для подсветки."""
    kcal_category = models.IntegerField(
        choices=KCAL_CATEGORIES, unique=True,
        verbose_name="Категория калорийности"
    )
    kcal_min    = models.PositiveIntegerField(verbose_name="Ккал — мин")
    kcal_max    = models.PositiveIntegerField(verbose_name="Ккал — макс")
    protein_min = models.PositiveIntegerField(verbose_name="Белки — мин, г")
    protein_max = models.PositiveIntegerField(verbose_name="Белки — макс, г")
    fat_min     = models.PositiveIntegerField(verbose_name="Жиры — мин, г")
    fat_max     = models.PositiveIntegerField(verbose_name="Жиры — макс, г")
    carbs_min   = models.PositiveIntegerField(verbose_name="Углеводы — мин, г")
    carbs_max   = models.PositiveIntegerField(verbose_name="Углеводы — макс, г")

    class Meta:
        verbose_name = "Норма КБЖУ"
        verbose_name_plural = "Нормы КБЖУ"
        ordering = ["kcal_category"]

    def __str__(self):
        return f"Норма {self.kcal_category} ккал"


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
# Справочники (Product, MealTime, RationNorm, RationTemplate) — общие.

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
    kcal_category = models.IntegerField(choices=KCAL_CATEGORIES, verbose_name="Категория калорийности")
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