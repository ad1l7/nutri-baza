"""Показывает ингредиенты, которых нет в справочнике INGREDIENT_ALIASES.

Такие названия попадают в состав как есть — не теряются, но и не чистятся.
Команда нужна после синхронизации с iiko: если появилось новое сырьё,
здесь его видно, и справочник можно дополнить.

    python manage.py unknown_ingredients
"""
from collections import Counter

from django.core.management.base import BaseCommand

from myapp.ingredient_aliases import INGREDIENT_ALIASES, split_ingredients
from myapp.models import Product


class Command(BaseCommand):
    help = "Ингредиенты, отсутствующие в справочнике INGREDIENT_ALIASES"

    def handle(self, *args, **options):
        counter = Counter()
        for product in Product.objects.exclude(composition=None).exclude(composition=""):
            for part in split_ingredients(product.composition):
                if part not in INGREDIENT_ALIASES:
                    counter[part] += 1

        if not counter:
            self.stdout.write("Все ингредиенты есть в справочнике.")
            return

        self.stdout.write(f"Нет в справочнике: {len(counter)} названий\n")
        for name, count in counter.most_common():
            self.stdout.write(f"  {count:4d}  {name}")
        self.stdout.write(
            "\nЭти названия попадают в состав без изменений. "
            "Если среди них есть требующие чистки — дополните INGREDIENT_ALIASES."
        )
