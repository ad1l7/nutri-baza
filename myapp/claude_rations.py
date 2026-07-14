"""
Генерация рационов через Claude (Anthropic API).

Claude ТОЛЬКО читает каталог блюд и нормы КБЖУ и предлагает состав рациона.
Ничего в базе он не меняет — это делает наш код по его ответу (в отдельной вкладке).
"""

import json
import anthropic
from django.conf import settings

MODEL = "claude-opus-4-8"

# Строгая схема ответа — Claude обязан вернуть ровно такую структуру
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "kcal_category": {"type": "integer", "enum": [1200, 1500, 1800, 2500]},
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "meal_name": {"type": "string"},
                    "dish_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["meal_name", "dish_ids"],
                "additionalProperties": False,
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["kcal_category", "meals", "reasoning"],
    "additionalProperties": False,
}

_SYSTEM = (
    "Ты — помощник-диетолог сервиса здорового питания O-Live. "
    "Твоя единственная задача — собирать суточные рационы из блюд, которые есть в каталоге. "
    "Ты работаешь только в своей вкладке и не управляешь остальной системой. "
    "Правила:\n"
    "1. Используй ТОЛЬКО блюда из переданного каталога, ссылайся на них по полю id.\n"
    "2. Собери рацион под одну из категорий калорийности (1200/1500/1800/2500) и старайся "
    "попасть в нормы КБЖУ для этой категории.\n"
    "3. Не повторяй одно и то же блюдо в рационе.\n"
    "4. Учитывай пожелания пользователя (аллергены, предпочтения, бюджет и т.п.).\n"
    "5. Разбей рацион на приёмы пищи (Завтрак, Обед, Ужин, Перекус — на твоё усмотрение).\n"
    "6. В поле reasoning кратко и по-русски объясни, почему выбрал именно такой состав: "
    "как попал в нормы КБЖУ, чем руководствовался, какие пожелания учёл."
)


def _build_catalog(products) -> list:
    """Компактный список блюд для передачи в Claude."""
    catalog = []
    for p in products:
        cats = ", ".join(str(c) for c in p.meal_categories.all())
        catalog.append({
            "id": p.pk,
            "name": p.name,
            "category": cats or "—",
            "kcal": round(float(p.kcal_per_serving or 0), 1),
            "protein": round(float(p.protein_per_serving or 0), 1),
            "fat": round(float(p.fat_per_serving or 0), 1),
            "carbs": round(float(p.carbs_per_serving or 0), 1),
            "cost": round(float(p.cost or 0)),
        })
    return catalog


def _build_norms(norms) -> list:
    return [
        {
            "kcal_category": n.kcal_category,
            "kcal": [n.kcal_min, n.kcal_max],
            "protein": [n.protein_min, n.protein_max],
            "fat": [n.fat_min, n.fat_max],
            "carbs": [n.carbs_min, n.carbs_max],
        }
        for n in norms
    ]


def generate_ration(wishes: str, products, norms) -> dict:
    """Возвращает предложение Claude в виде dict согласно _OUTPUT_SCHEMA.
    Бросает исключение при ошибке API."""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("Не задан ANTHROPIC_API_KEY в настройках/.env")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    catalog = _build_catalog(products)
    norms_data = _build_norms(norms)

    user_prompt = (
        f"Пожелания пользователя:\n{wishes.strip() or '(без особых пожеланий)'}\n\n"
        f"Нормы КБЖУ по категориям (мин–макс):\n{json.dumps(norms_data, ensure_ascii=False)}\n\n"
        f"Каталог блюд (КБЖУ и себестоимость — на порцию):\n"
        f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
        "Собери один суточный рацион. Верни строго JSON по заданной схеме."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        # effort=medium ускоряет сборку (меньше "размышлений") при сохранении Opus 4.8.
        # При необходимости качества верни "high"; для скорости — "low".
        output_config={
            "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
            "effort": "medium",
        },
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude отклонил запрос (safety).")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("Пустой ответ от Claude.")

    return json.loads(text)
