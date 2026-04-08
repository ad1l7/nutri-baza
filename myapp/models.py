from django.db import models


class Allergen(models.Model):
    name = models.CharField(max_length=200, verbose_name="Аллерген")

    class Meta:
        verbose_name = "Аллерген"
        verbose_name_plural = "Аллергены"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.CharField(max_length=200, verbose_name="Категория")
    name = models.CharField(max_length=300, verbose_name="Наименование")
    photo = models.ImageField(
        upload_to="products/", null=True, blank=True,
        verbose_name="Фото"
    )
    cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Себестоимость ФЗ"
    )
    net_weight = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True,
        verbose_name="Масса нетто (одной ед., г)"
    )
    packing = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Кратность / Фасовка"
    )
    composition = models.TextField(null=True, blank=True, verbose_name="Состав")
    allergens = models.ManyToManyField(
        "Allergen", blank=True, verbose_name="Аллергены"
    )

    protein = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Белки")
    fat = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Жиры")
    carbs = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Углеводы")
    kcal_per_100 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Ккал на 100г")
    kj_per_100 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="КДж на 100г")

    protein_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Белки на 1 порц.")
    fat_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Жиры на 1 порц.")
    carbs_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Углеводы на 1 порц.")
    kcal_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Ккал на 1 порц.")
    kj_per_serving = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="КДж на 1 порц.")

    class Meta:
        verbose_name = "Продукт"
        verbose_name_plural = "Продукты"
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.category} — {self.name}"


# ── Рационы ──────────────────────────────────────────────

KCAL_CATEGORIES = [
    (1200, '1200 ккал'),
    (1500, '1500 ккал'),
    (1800, '1800 ккал'),
    (2500, '2500 ккал'),
]

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

# Порядок отображения слотов
SLOT_ORDER = {k: i for i, (k, _) in enumerate(SLOT_TYPES)}


class Ration(models.Model):
    name = models.CharField(max_length=300, verbose_name="Название рациона")
    date = models.DateField(verbose_name="Дата")
    kcal_category = models.IntegerField(choices=KCAL_CATEGORIES, verbose_name="Категория калорийности")
    notes = models.TextField(blank=True, null=True, verbose_name="Примечания")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Рацион"
        verbose_name_plural = "Рационы"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.name} ({self.date})"

    def total_kcal(self):
        return sum(
            s.product.kcal_per_serving or 0
            for s in self.slots.select_related("product")
            if s.product
        )

    def total_protein(self):
        return sum(
            s.product.protein_per_serving or 0
            for s in self.slots.select_related("product")
            if s.product
        )

    def total_fat(self):
        return sum(
            s.product.fat_per_serving or 0
            for s in self.slots.select_related("product")
            if s.product
        )

    def total_carbs(self):
        return sum(
            s.product.carbs_per_serving or 0
            for s in self.slots.select_related("product")
            if s.product
        )


class RationSlot(models.Model):
    ration = models.ForeignKey(
        Ration, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Рацион"
    )
    slot_type = models.CharField(
        max_length=50, choices=SLOT_TYPES,
        verbose_name="Тип приёма пищи"
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
        ordering = ["order"]

    def __str__(self):
        return f"{self.get_slot_type_display()} — {self.product or 'пусто'}"