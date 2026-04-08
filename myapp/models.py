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

    # На 100г
    protein = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Белки")
    fat = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Жиры")
    carbs = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Углеводы")
    kcal_per_100 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="Ккал на 100г")
    kj_per_100 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, verbose_name="КДж на 100г")

    # На 1 порцию
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