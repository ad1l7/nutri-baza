"""
Генерация рационов через Claude (Anthropic API).

Claude ТОЛЬКО читает каталог блюд и нормы КБЖУ и предлагает состав рациона.
Ничего в базе он не меняет — это делает наш код по его ответу (в отдельной вкладке).
"""

import copy
import json
import logging
import time
import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"

# Бюджет токенов на ОДИН запрос сборки рациона (размышления + итоговый JSON).
# Чтобы увеличить — поменяйте только это число, потом перезапустите gunicorn.
# Потолок Opus 4.8 — 128000. Больше = меньше риск обрыва на сложных рационах;
# на СКОРОСТЬ не влияет (её определяет output_config.effort ниже).
MAX_TOKENS = 64000

# Строгая схема ответа — Claude обязан вернуть ровно такую структуру
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        # enum подставляется в generate_ration из переданных калоражей
        "kcal_category": {"type": "integer"},
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
    "2. Собери рацион под заданную категорию калорийности и старайся "
    "попасть в нормы КБЖУ для этой категории.\n"
    "3. Не повторяй одно и то же блюдо в рационе.\n"
    "4. Учитывай пожелания пользователя (аллергены, предпочтения, бюджет и т.п.).\n"
    "5. Приёмы пищи ФИКСИРОВАНЫ пользователем. Раскладывай блюда РОВНО по приёмам, "
    "которые указаны в задании, используя их точные названия. Не придумывай своих "
    "приёмов пищи и не пропускай ни один.\n"
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


def generate_ration(wishes: str, products, norms, meal_times=None) -> dict:
    """Возвращает предложение Claude в виде dict согласно схеме.

    meal_times — список названий фиксированных приёмов пищи рациона. Если задан,
    Claude обязан разложить блюда РОВНО по ним (структура приёмов не меняется):
    названия форсируются через enum в схеме.
    Бросает исключение при ошибке API."""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("Не задан ANTHROPIC_API_KEY в настройках/.env")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    catalog = _build_catalog(products)
    norms_data = _build_norms(norms)

    schema = copy.deepcopy(_OUTPUT_SCHEMA)

    # Калорийности берём из переданных калоражей — список задаётся во вкладке
    # «Калоражи», а не зашит в код.
    kcal_values = [n["kcal_category"] for n in norms_data if n["kcal_category"]]
    if kcal_values:
        schema["properties"]["kcal_category"]["enum"] = kcal_values

    # Если приёмы пищи фиксированы — форсируем их названия через enum в схеме
    meals_line = "Собери один суточный рацион. Верни строго JSON по заданной схеме."
    if meal_times:
        schema["properties"]["meals"]["items"]["properties"]["meal_name"]["enum"] = list(meal_times)
        meals_line = (
            "ВАЖНО: приёмы пищи ФИКСИРОВАНЫ и менять их нельзя. Разложи блюда РОВНО по "
            "этим приёмам пищи, используя эти точные названия и не придумывая других:\n"
            + ", ".join(meal_times) + ".\n"
            "Каждый приём пищи должен присутствовать ровно один раз и содержать хотя бы "
            "одно блюдо. Верни строго JSON по заданной схеме."
        )

    user_prompt = (
        f"Пожелания пользователя:\n{wishes.strip() or '(без особых пожеланий)'}\n\n"
        f"Нормы КБЖУ по категориям (мин–макс):\n{json.dumps(norms_data, ensure_ascii=False)}\n\n"
        f"Каталог блюд (КБЖУ и себестоимость — на порцию):\n"
        f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
        + meals_line
    )

    # Замер: если сборка снова начнёт тормозить — причина будет видна в логах,
    # а не в догадках. Читать: journalctl -u gunicorn -f | grep claude
    started = time.monotonic()
    logger.info(
        "claude: старт | блюд в каталоге=%d | приёмов=%d | схема с enum=%s",
        len(catalog), len(meal_times or []), bool(meal_times),
    )

    # Стримим, а не ждём ответ целиком: при большом max_tokens неблокирующий
    # запрос упирается в HTTP-таймаут SDK. get_final_message() собирает ответ.
    with client.messages.stream(
        model=MODEL,
        # Бюджет общий на "размышления" + JSON. При 16000 адаптивное мышление
        # успевало съесть весь лимит и текстовый блок не возвращался вовсе —
        # отсюда была "Пустой ответ от Claude". Значение — в MAX_TOKENS вверху файла.
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        # effort=medium ускоряет сборку (меньше "размышлений") при сохранении Opus 4.8.
        # При необходимости качества верни "high"; для скорости — "low".
        output_config={
            "format": {"type": "json_schema", "schema": schema},
            "effort": "medium",
        },
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        response = stream.get_final_message()

    elapsed = time.monotonic() - started
    usage = response.usage
    # Выход = размышления + JSON. Именно он, а не размер каталога, определяет
    # время: замеры показали ~9000 токенов выхода ≈ 2 минуты.
    logger.info(
        "claude: готово за %.1f сек | вход=%d | выход=%d | stop_reason=%s",
        elapsed, usage.input_tokens, usage.output_tokens, response.stop_reason,
    )
    if elapsed > 90:
        logger.warning(
            "claude: сборка заняла %.0f сек — это ненормально долго. "
            "Проверьте выход в токенах выше: если он мал, тормозил сам API, "
            "если велик — модель много «размышляла» (лечится output_config.effort).",
            elapsed,
        )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude отклонил запрос (safety).")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        # Без деталей эту ошибку невозможно диагностировать — показываем причину.
        usage = response.usage
        raise RuntimeError(
            f"Claude не вернул JSON (stop_reason={response.stop_reason}, "
            f"выдано {usage.output_tokens} из {MAX_TOKENS} токенов). "
            "Если stop_reason=max_tokens — рацион слишком сложный: упростите "
            "пожелания, сократите число приёмов пищи или поднимите max_tokens."
        )

    return json.loads(text)
