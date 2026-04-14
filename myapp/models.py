from django.db import models


class Allergen(models.Model):
    name = models.CharField(max_length=200, verbose_name="Аллерген")

    class Meta:
        verbose_name = "Аллерген"
        verbose_name_plural = "Аллергены"
        ordering = ["name"]

    def __str__(self):
        return self.name


SLOT_TYPES = [
    ('breakfast_250', 'Завтрак 250–350 ккал'),
    ('breakfast_400', 'Завтрак 400–500 ккал'),
    ('second_400',    'Второе 400–500 ккал'),
    ('second_500',    'Второе 500–600 ккал'),
    ('soup_200',      'Суп 200 ккал'),
    ('soup_300',      'Суп 300 ккал'),
    ('salad_150',     'Салат 150–250 ккал'),
    ('salad_250',     'Салат 250–350 ккал'),
    ('dessert_100',   'Выпечка/Десерт 100–250 ккал'),
    ('dessert_300',   'Выпечка/Десерт 300–350 ккал'),
    ('smoothie',      'Смузи 100–150 ккал'),
    ('sandwich',      'Сэндвич 300–350 ккал'),
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
    # Основные поля
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

    # iiko интеграция
    iiko_id = models.CharField(max_length=50, null=True, blank=True, unique=True, verbose_name="iiko UUID")
    iiko_category = models.CharField(max_length=300, null=True, blank=True, verbose_name="Категория iiko")
    iiko_synced_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя синхронизация")

    class Meta:
        verbose_name = "Продукт"
        verbose_name_plural = "Продукты"
        ordering = ["name"]

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
    template = models.ForeignKey(
        RationTemplate, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Шаблон"
    )
    slot_type = models.CharField(max_length=50, choices=SLOT_TYPES, verbose_name="Тип слота")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Слот шаблона"
        verbose_name_plural = "Слоты шаблона"
        ordering = ["order"]

    def __str__(self):
        return f"{self.template} / {self.get_slot_type_display()}"


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Рацион"
        verbose_name_plural = "Рационы"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class RationSlot(models.Model):
    ration = models.ForeignKey(
        Ration, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Рацион"
    )
    slot_type = models.CharField(max_length=50, choices=SLOT_TYPES, verbose_name="Категория блюда")
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ration_slots", verbose_name="Блюдо"
    )
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Слот рациона"
        verbose_name_plural = "Слоты рациона"
        ordering = ["order"]

    def __str__(self):
        return f"{self.get_slot_type_display()} — {self.product or 'пусто'}"