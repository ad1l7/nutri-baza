# ERP ↔ iiko напрямую: выгрузка блюд для этикеток

Документ для агента ERP-системы. Задача — научить ERP забирать данные блюд
Olive напрямую из iiko. Промежуточный API Olive, через который ERP получала
каталог раньше, уже отключён — единственный источник теперь iiko.

Всё описанное — рабочая схема: именно так база Olive уже больше года тянет
данные из того же iiko. Референсный код приложен целиком (приложения A и B),
здесь — что из него брать, что выкинуть и где грабли.

---

## 1. Архитектура: было и будет

Сейчас: `iiko → база Olive → (API с токеном) → ERP`.
Будет: `iiko → ERP` напрямую; цепочка через Olive отключается.

У iiko **два разных API**, и для этикеток нужны оба:

| | **iiko Cloud API** | **iiko Server API (resto)** |
|---|---|---|
| Адрес | `https://api-ru.iiko.services` | `https://<сервер>.iiko.it/resto` |
| Авторизация | `apiLogin` + `appId` + `clientSecret` → Bearer-токен | логин/пароль → key-токен |
| Что даёт | внешнее меню: названия, артикулы, вес порции, КБЖУ на 100 г, аллергены | технологические карты → **состав блюда** |
| Формат | JSON, POST | JSON, GET/POST c `?key=` |

Состав есть **только** в Server API: Cloud внешнего меню состава не отдаёт
(там лишь description, который на кухне не ведут). Поэтому пропустить
Server-часть нельзя — без неё не будет состава на этикетке.

---

## 2. Доступы

Понадобятся 8 значений (сами значения передаются отдельно, не в этом файле):

```
IIKO_CLOUD_API_KEY    # apiLogin из iikoWeb
IIKO_APP_ID           # из кабинета разработчика iiko
IIKO_CLIENT_SECRET    # оттуда же
IIKO_ORG_ID           # UUID организации
IIKO_EXTERNAL_MENU_ID # id внешнего меню (там живут блюда Olive)
IIKO_SERVER_URL       # https://<сервер>.iiko.it/resto
IIKO_SERVER_LOGIN     # пользователь iiko Server
IIKO_SERVER_PASSWORD
```

**Нужен ли отдельный ключ для ERP?** Технически можно работать на тех же
ключах, что и Olive, — iiko это не запрещает. Но правильно завести для ERP
**свои** `apiLogin`/`appId` в iikoWeb и **отдельного пользователя** iiko
Server (с правами только на чтение номенклатуры и техкарт). Причины:

- отзыв ключа одной системы не роняет вторую;
- в логах iiko видно, кто именно ходил;
- у Cloud API лимиты частоты считаются на ключ — два потребителя на одном
  ключе будут толкаться.

Новое **внешнее меню создавать не нужно** — ERP читает то же
`IIKO_EXTERNAL_MENU_ID`, что и Olive: это и есть список блюд с их КБЖУ.

**Критично про сроки:** старый способ авторизации Cloud
(`POST /api/1/access_token` только по `apiLogin`) iiko отключает
**~29.08.2026** — через несколько дней. Сразу делайте только новую схему:

```
POST https://api-ru.iiko.services/api/v2/access_token
{"apiLogin": "...", "appId": "...", "clientSecret": "..."}
→ {"token": "..."}   # Bearer, живёт ~1 час, получать заново по 401
```

---

## 3. Что ERP реально нужно (и что — нет)

Гипотеза «достаточно состава, названия и КБЖУ» **почти** верна. Проверка по
рабочему макету этикетки — на ней печатаются:

| Данные | Откуда в iiko | Обяз. |
|---|---|---|
| Название блюда (очищенное) | меню Cloud, поле `name` + чистка (раздел 6) | да |
| Состав (очищенный) | техкарты Server (раздел 5) | да |
| БЖУ на порцию, ккал, кДж | считается: на 100 г × вес / 100 | да |
| **Масса нетто, г** | меню Cloud, `portionWeightGrams` | **да — про неё в гипотезе забыли, а на этикетке она есть** |
| Артикул | меню Cloud `sku` / номенклатура `num` | да — не печатается, но по нему оператор ищет блюдо |
| Аллергены | меню Cloud, `item.allergens` | нет — на текущем макете общая фраза-дисклеймер, но задел полезный |

Чего из синхронизации Olive **брать не нужно** (в референсном коде это есть —
выкидывайте смело):

- **себестоимость** (OLAP-отчёт `get_cost_report`, `_parse_cost_report`,
  `_lookup_cost`) — для этикетки не нужна, и это самая тяжёлая и хрупкая
  часть кода;
- **фото блюд** (`_download_photo`, `_photo_url_changed`) — на этикетке
  картинки нет;
- **категории меню** (`_SLOT_LABEL_TO_KEY`, `_pick_category`,
  `_normalize_label`, `IikoCategoryMap`) — это раскладка блюд по слотам
  рационов сайта Olive, к этикеткам отношения не имеет;
- **цена продажи, наценки** — внутренняя механика каталога Olive.

Из ~1000 строк референса рабочими для ERP остаются примерно 400.

---

## 4. Пайплайн синхронизации

Порядок шагов — как в референсе (`sync_products_from_iiko`), с выкинутым лишним:

**Шаг 1. Внешнее меню (Cloud).**
`POST /api/2/menu/by_id` c `{"externalMenuId", "organizationIds": [org],
"priceCategoryId": "00000000-0000-0000-0000-000000000000", "version": 2}`.
Разбор — функция `_extract_menu_items` из референса: обходит дерево
`itemCategories` рекурсивно, из `itemSizes[0]` берёт
`portionWeightGrams` и `nutritionPerHundredGrams`
(`energy`/`proteins`/`fats`/`carbs`). Нюансы, которые уже отлажены:

- `nutritionPerHundredGrams` бывает и объектом, и списком — берётся первый
  элемент; фолбэк — `nutritions[0]`;
- кДж в iiko нет — считается `kcal × 4.184`;
- «на порцию» в iiko нет — считается `на_100г × вес / 100`, округление до 2 знаков;
- блюдо может входить в несколько категорий меню — не создавайте дубли
  (в референсе это ветка `if product_id in result`);
- артикул — `sku` / `code` на item или size, где найдётся.

**Шаг 2. Номенклатура (Cloud).** `POST /api/1/nomenclature` → отображение
`uuid → num`. Нужна как фолбэк для блюд, у которых артикула нет в меню.
Один дешёвый запрос — оставить.

**Шаг 3. Состав (Server).** Для каждого блюда из меню:

```
GET /resto/api/auth?login=...&pass=...        → key (один на всю сессию!)
GET /resto/api/v2/entities/products/list?includeDeleted=false&key=...
GET /resto/api/v2/assemblyCharts/getTree?date=YYYY-MM-DD&productId=<uuid>&key=...
    (по одному запросу на блюдо, ~270 штук — пулом потоков, 8 воркеров)
GET /resto/api/auth/logout?key=...            → ОБЯЗАТЕЛЬНО (раздел 7)
```

Сборка состава из дерева — функции `_tree_leaves` и `_composition_from_tree`
референса, переносить их целиком, они самое ценное здесь. Что они делают и
почему именно так:

- **`getTree`, а не `getPrepared`**: prepared-карта не заходит в
  полуфабрикаты со списанием DIRECT и теряет их ингредиенты. Дерево
  раскрываем сами: лист = продукт без собственной сборки;
- на продукт бывает **несколько карт** (разные периоды действия) — берётся
  действующая (`dateTo == null`), иначе с самой поздней `dateFrom`;
- количества перемножаются по дереву (`amountOut → amountMiddle → amountIn`),
  сортировка **по убыванию массы** — порядок ингредиентов на этикетке обязан
  идти от основного к второстепенному;
- set `visited` защищает от циклов в дереве, но у него есть **известный
  побочный эффект**: сырьё, входящее и в блюдо, и в его полуфабрикат (соль,
  масло — обычное дело), засчитывается только по первому вхождению. Ингредиент
  из состава не пропадает, но недобирает массу и может встать не на своё место
  в порядке. Воспроизводится так: соль 0,01 напрямую + 0,05 в соусе даёт 0,01,
  и соль уходит ниже масла (0,05). Правильное поведение — суммировать все
  вхождения, помечая `visited` только узлы-сборки, а не листья. Пока **не
  исправлено ни здесь, ни в Olive**: чинить надо синхронно, иначе составы
  разъедутся. Порядок действий — сначала сверка на текущем (совпадающем)
  поведении, потом правка с обеих сторон одним заходом;
- если карты нет вообще — фолбэк на `description` продукта
  (`_parse_description`: бывает строкой, JSON-списком блоков или dict).

**Шаг 4. Чистка** (разделы 5–6). **Шаг 5. Запись в свою таблицу** (у вас уже
есть `ExternalProduct` из первой интеграции — она подходит как есть, меняется
только источник данных: вместо API Olive — этот пайплайн).

Ключ сопоставления при повторных синках — **артикул**, а не внутренний uuid:
в iiko блюда порой пересоздают (например, при перестройке подгрупп), uuid
меняется, артикул остаётся. Референс сначала ищет по артикулу (только если он
уникален с обеих сторон), потом по uuid — повторите эту логику.

---

## 5. Чистка состава — два уровня

### Уровень 1: структурный (при сборке из техкарты)

Уже внутри `_composition_from_tree`:

- **выкинуть упаковку**: всё, что начинается на `У*` (контейнеры, крышки,
  этикетки — в техкарте они есть, в составе еды им не место);
- **выкинуть техпозиции**: название содержит «смесь газ» (газомодифицированная
  среда упаковки);
- **срезать складские префиксы** `С* `, `П* `, `Б* `, `ПП* ` и т.п. —
  регулярка `^[А-ЯЁA-Z]{1,3}\*\s*`;
- схлопнуть дубли по нормализованному имени (пробелы, регистр).

### Уровень 2: словарный (INGREDIENT_ALIASES)

После уровня 1 названия остаются «складскими»: «Молоко 3,2% л»,
«Специя Перец черный горошек», «Яйцо фудзавод шт». Их приводит в человеческий
вид словарь `INGREDIENT_ALIASES` — **309 записей, собранных вручную и
вычитанных 15.08.2026** (приложение B, переносить целиком вместе с функциями
`split_ingredients` / `clean_composition`). Правила, по которым он строился:

- убрать числа, проценты, единицы (л/шт/кг/мл), сорта (в/с, 1с), складские
  пометки («фудзавод», «дорогая», «в ассортименте», «неисп»);
- слово-категорию в начале убирать только если без него понятно:
  «Специя Перец черный горошек» → «Перец черный», но «Соус терияки» остаётся;
- уточнения, меняющие продукт, сохранять («Мука пшеничная цельнозерновая»),
  помол/цвет/поставщика — убирать («Соль мелкая» → «Соль»).

Механика применения (`clean_composition`): разделитель ингредиентов — строго
«запятая + пробел» (десятичные запятые внутри названий идут без пробела:
«Молоко 3,2%» — поэтому разбор однозначный); подмена по словарю; дубли после
подмены схлопываются («Соль мелкая» + «Соль крупная» → одна «Соль»);
**порядок сохраняется** — он несёт убывание массы.

Два железных правила:

1. **Незнакомое название остаётся как есть.** Ингредиент не имеет права
   исчезнуть из состава ни при каких обстоятельствах — это пищевая
   маркировка.
2. **Хранить оба варианта**: сырой состав (для сверки с iiko) и чистый
   (для печати). Olive так и делает (`composition` / `composition_clean`).

**Сопровождение — важно.** На кухне появляется новое сырьё, словарь отстаёт.
В Olive есть команда `unknown_ingredients`: пробегает по сырым составам и
показывает названия, которых нет в словаре. Сделайте у себя такую же
(15 строк, шаблон в приложении B внизу) и прогоняйте после синхронизаций.
И учтите: с этого момента **словарь ERP живёт своей жизнью** — копия в Olive
обновляться не будет, сверять их между собой не нужно.

### Чистка названия блюда

Названия в iiko несут служебные пометки: «ПП* Упак Сырники (1порц)».
На этикетку идёт очищенное:

```python
def clean_name(name):
    result = (name or "").replace("ПП* Упак ", "").replace("ПП*Упак ", "")
    for tail in (" (1порц)", " (1шт)", "(1порц)", "(1шт)"):
        result = result.replace(tail, "")
    return result.strip()
```

Хранить тоже оба варианта: сырое (для поиска/сверки) и чистое (для печати).

---

## 6. Риски и как их обходить

Всё из этого списка Olive прошла на себе.

1. **Артикулы переиспользуются после удаления блюда.** У удалённого блюда и
   у живого может оказаться один `num` (реальный случай: `00348` — удалённый
   «Чебурек с мясом и джусаем» и живая «Белая рыба со шпинатом»). Любой поиск
   продукта по артикулу без фильтра удалённых вернёт чужую карточку и чужую
   техкарту. Правило: `productId` (uuid) из меню — единственный надёжный ключ
   для запросов в iiko; `includeDeleted=false` в
   `/entities/products/list` обязателен; артикул годится только как
   человекочитаемая метка и как ключ сопоставления с **вашей** таблицей — и то
   с проверкой, что название не изменилось до неузнаваемости.

2. **Лицензии iiko Server.** Токен `/resto/api/auth` занимает слот лицензии
   API. Не сделать `logout` — слот висит до таймаута, и следующая
   синхронизация (или синхронизация Olive!) может не войти. Logout — в
   `finally`, всегда, даже после ошибки.
3. **Одновременные синхронизации двух систем.** Olive продолжит синкать iiko
   для своего сайта. Разнесите расписания (например, Olive днём по кнопке,
   ERP — ночью по крону) — меньше шансов столкнуться на лицензиях Server.
4. **Rate limit Cloud.** На 429 и 503 — пауза и повтор (в референсе
   `_request_with_retry`: 3 попытки, пауза 5с × номер попытки). Между
   запросами техкарт — не злоупотреблять параллельностью: 8 воркеров
   проверены, 50 — напрашиваться на бан.
5. **Частота.** Раз в сутки ночью + кнопка «вручную» — за глаза: составы
   меняются редко. Чаще раза в час не ходить вообще.
6. **Смерть v1-авторизации ~29.08.2026.** Только `/api/v2/access_token`
   с `appId`+`clientSecret`. Токен протухает (~1 час) — по 401 получать новый
   и повторять запрос.
7. **Ничего не удалять автоматически.** Блюдо пропало из меню iiko — пометьте
   `is_active = False` и живите дальше. Olive однажды удаляла автоматически и
   поплатилась потерей связей; теперь только лог кандидатов.
8. **`null` ≠ 0.** Незаполненные КБЖУ/вес приходят как null — печатать «—»,
   не ноль и не падать.
9. **Пустой состав = блюдо не для печати.** Если после техкарт и description
   состав пуст — не показывать блюдо в списке печати (Olive фильтрует именно так).
10. **Один сбой ≠ падение синка.** Ошибка на одном блюде логируется и
   пропускается, остальные продолжают обрабатываться.

---

## 7. План перехода и приёмка

Промежуточный API Olive **уже закрыт** — сверяться с ним больше нельзя.
Эталон для приёмки у вас свой: таблица `ExternalProduct`, в которой лежит
последний снимок каталога, полученный от Olive до отключения. Он собран той
же логикой, что описана здесь, поэтому расхождение = ошибка переноса.

1. Прямой пайплайн (разделы 4–5) пишет результат **в отдельную таблицу или
   с отдельным `source`**, не трогая ту копию, из которой сейчас печатают.
2. Прогон сверки: для каждого блюда сравнить новый результат со старым
   снимком. Поля: очищенное название, состав, масса нетто, все КБЖУ.
   Каждое расхождение разбирать до нуля — типичные причины ниже.
3. Только когда сверка чистая — переключить печать на прямой источник,
   день-два понаблюдать, затем удалить старую копию.

Ожидаемые (нормальные) расхождения — их не считать ошибкой, но глазами
проверить каждое:

- **блюдо изменилось в iiko** с момента последнего снимка (сверьте с
  карточкой в самой iiko — новые данные правильные);
- **новое сырьё, которого нет в словаре**: в старом снимке чистое название,
  в новом — складское. Это сигнал дополнить `INGREDIENT_ALIASES`, а не
  ошибка кода.

Ошибки переноса, которые сверка ловит чаще всего: потерянные ингредиенты
(взяли `getPrepared` вместо `getTree`), состав в неверном порядке (не
отсортировали по массе), упаковка в составе (не отфильтровали `У*`),
КБЖУ «на 100 г» вместо «на порцию».

---

## Приложение A. Референс: рабочая синхронизация Olive ↔ iiko (`iiko_sync.py`)

Что выкинуть при переносе — см. раздел 3. Забирать: клиенты
`IikoCloudClient`/`IikoServerClient`, `_request_with_retry`,
`_extract_menu_items`, `_tree_leaves`, `_composition_from_tree`,
`_ingredient_excluded`, `_clean_ingredient`, `_parse_description`,
retry/rate-limit константы, логику сопоставления по артикулу из
`sync_products_from_iiko` (шаги 6–7).

```python
"""
iiko_sync.py — умная синхронизация продуктов из iiko в O-Live.

Ключ синхронизации: артикул (num) из iiko — поле iiko_sku в Product.

Логика обновления:
  - Новые блюда (нет в БД) → создаём + скачиваем фото
  - Существующие блюда → сравниваем поля, обновляем ТОЛЬКО если что-то изменилось
  - Фото → скачиваем только если URL изменился или фото нет
  - Аллергены → берём из item.allergens, get_or_create по имени
  - Удалённые из iiko → удаляем из БД

Состав блюда — из технологической карты iiko Server
(/api/v2/assemblyCharts/getPrepared): iiko сам раскрывает дерево ТК до конечного
сырья. Из списка убираем упаковку (У*) и «Смесь газ», срезаем префиксы (С*, П*
и т.п.), убираем дубли. Если prepared-карты нет — фолбэк на description продукта.
"""

import re
from decimal import Decimal
import time
import hashlib
import requests
import logging
import json as _json
import os
from concurrent.futures import ThreadPoolExecutor
from django.utils import timezone as dj_timezone
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# ── Защита от блокировки ──────────────────────────────────────────────────────
RATE_LIMIT_DELAY  = 0.2
MAX_RETRIES       = 3
RETRY_DELAY       = 5
MIN_SYNC_INTERVAL = 5  # временно уменьшено для тестирования категорий
COMPOSITION_WORKERS = 8  # параллельных запросов техкарт к iiko Server

_last_sync_time = 0

# ── Точное совпадение название группы iiko → ключ SLOT_TYPES ─────────────────
_SLOT_LABEL_TO_KEY = {
    # Старые (дробные) названия из iiko → новые объединённые категории сайта
    'Завтрак 250–350 ккал':        'breakfast',
    'Завтрак 400–500 ккал':        'breakfast',
    'Второе 400–500 ккал':         'hot_400',
    'Второе 500–600 ккал':         'hot_500',
    'Суп 200 ккал':                'soup',
    'Суп 300 ккал':                'soup',
    'Салат 150–250 ккал':          'salad',
    'Салат 250–350 ккал':          'salad',
    'Выпечка/Десерт 100–250 ккал': 'dessert',
    'Выпечка/Десерт 300–350 ккал': 'dessert',
    'Смузи 100–150 ккал':          'smoothie',
    'Сэндвич 300–350 ккал':        'sandwich',
    # Новые названия (на случай если в iiko переименуют как на сайте)
    'Завтрак':          'breakfast',
    'Горячее 400-500':  'hot_400',
    'Горячее 500-600':  'hot_500',
    'Суп':              'soup',
    'Салат':            'salad',
    'Выпечка/Десерт':   'dessert',
    'Смузи':            'smoothie',
    'Сэндвичи':         'sandwich',
}


def _normalize_label(s: str) -> str:
    """Приводит название группы к единому виду для сравнения:
    разные виды тире/дефиса → '-', убираем слово 'ккал', лишние пробелы, регистр."""
    s = s.strip().lower()
    s = re.sub(r'[‐-―−]', '-', s)
    s = re.sub(r'\s*ккал\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


_SLOT_LABEL_TO_KEY_NORM = {
    _normalize_label(label): key for label, key in _SLOT_LABEL_TO_KEY.items()
}


def _build_label_to_key() -> dict:
    """Нормализованное сопоставление {название_категории_iiko: slot_key}.
    Берёт встроенные значения из кода + редактируемые из админки (БД),
    записи из БД имеют приоритет."""
    result = dict(_SLOT_LABEL_TO_KEY_NORM)  # встроенные дефолты
    try:
        from .models import IikoCategoryMap
        for row in IikoCategoryMap.objects.all():
            result[_normalize_label(row.iiko_name)] = row.slot_key
    except Exception as e:
        logger.warning(f"Не удалось загрузить сопоставление категорий из БД: {e}")
    return result


def _pick_category(menu_info: dict, label_to_key: dict = None) -> tuple:
    """Блюдо может входить сразу в несколько категорий внешнего меню
    (например, ещё в техническую категорию типа 'ПП Упак').
    Возвращает (название_категории_для_отображения, slot_key_или_None) —
    выбираем первую категорию, совпавшую с категорией сайта, иначе первую попавшуюся."""
    if label_to_key is None:
        label_to_key = _SLOT_LABEL_TO_KEY_NORM
    cat_names = menu_info.get("category_names") or []
    if not cat_names and menu_info.get("category_name"):
        cat_names = [menu_info["category_name"]]

    for cn in cat_names:
        cn = (cn or "").strip()
        if not cn:
            continue
        slot_key = label_to_key.get(_normalize_label(cn))
        if slot_key:
            return cn, slot_key

    first = next((cn.strip() for cn in cat_names if cn and cn.strip()), "")
    return first, None

_COMPARE_FIELDS = [
    "name", "article", "iiko_category", "packing", "net_weight",
    "kcal_per_100", "protein", "fat", "carbs", "kj_per_100",
    "kcal_per_serving", "protein_per_serving", "fat_per_serving",
    "carbs_per_serving", "kj_per_serving", "composition", "cost",
]


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _round_for_compare(val):
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return val


def _fields_changed(product, new_fields: dict) -> tuple:
    changed = []
    for field in _COMPARE_FIELDS:
        if field not in new_fields:
            continue
        old_val = getattr(product, field, None)
        new_val = new_fields[field]
        if isinstance(new_val, float) or isinstance(old_val, float):
            if _round_for_compare(old_val) != _round_for_compare(new_val):
                changed.append(field)
        else:
            old_str = str(old_val) if old_val is not None else ""
            new_str = str(new_val) if new_val is not None else ""
            if old_str != new_str:
                changed.append(field)
    return bool(changed), changed


def _request_with_retry(method, url, **kwargs):
    resp = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = getattr(requests, method)(url, **kwargs)
            if resp.status_code in (429, 503):
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"HTTP {resp.status_code} — ждём {wait}с (попытка {attempt+1})")
                time.sleep(wait)
                continue
            return resp
        except requests.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            raise
    return resp


def _parse_description(desc) -> str:
    if not desc:
        return ""
    if isinstance(desc, str):
        try:
            desc = _json.loads(desc)
        except Exception:
            return desc.strip()
    if isinstance(desc, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in desc
        ).strip()
    if isinstance(desc, dict):
        return desc.get("text", str(desc)).strip()
    return str(desc).strip()


# ── Состав из технологической карты ──────────────────────────────────────────

# Префикс вида "С* ", "П* ", "Б* ", "ПП* " в начале названия продукта iiko
_INGR_PREFIX_RE = re.compile(r'^[А-ЯЁA-Z]{1,3}\*\s*')


def _ingredient_excluded(name: str) -> bool:
    """Упаковка (У*) и техпозиции типа «Смесь газ» — не еда, в состав не идут."""
    n = (name or '').strip()
    if n.startswith('У*'):
        return True
    if 'смесь газ' in n.lower():
        return True
    return False


def _clean_ingredient(name: str) -> str:
    """Срезает префикс 'С* '/'П* '/... и лишние пробелы."""
    return _INGR_PREFIX_RE.sub('', (name or '').strip()).strip()


def _tree_leaves(root_pid: str, charts: list) -> list:
    """Рекурсивно обходит дерево ТК (getTree) от корневого блюда и возвращает
    список листьев [(productId, effective_amount)] — конечное сырьё.

    Лист = продукт, у которого в дереве нет своего узла-сборки. Так мы обходим
    ограничение getPrepared: если полуфабрикат-основа (Б*/П*) списывается
    напрямую (DIRECT), getPrepared в него не заходит и теряет ингредиенты,
    а в дереве узел есть — и мы раскрываем его сами.
    """
    # На один продукт может быть несколько карт (разные периоды действия) —
    # берём актуальную: сначала действующую (dateTo=None), затем с поздней dateFrom.
    node_by_product = {}
    for c in charts or []:
        apid = c.get("assembledProductId")
        if not apid:
            continue
        cur = node_by_product.get(apid)
        if cur is None:
            node_by_product[apid] = c
        elif (c.get("dateTo") is None and cur.get("dateTo") is not None) or \
             (str(c.get("dateFrom") or "") > str(cur.get("dateFrom") or "")):
            node_by_product[apid] = c

    leaves = []
    visited = set()

    def walk(pid, amount):
        if pid in visited:
            return
        visited.add(pid)
        node = node_by_product.get(pid)
        if not node:  # нет своей сборки → лист (конечное сырьё)
            leaves.append((pid, amount))
            return
        for it in node.get("items") or []:
            sub = it.get("productId")
            if not sub:
                continue
            try:
                a = float(it.get("amountOut") or it.get("amountMiddle")
                          or it.get("amountIn") or 0)
            except (TypeError, ValueError):
                a = 0.0
            walk(sub, (amount * a) if amount else a)

    walk(root_pid, 1.0)
    return leaves


def _composition_from_tree(root_pid: str, charts: list, products_by_id: dict) -> str:
    """Строка состава из дерева ТК: раскрываем до сырья, убираем упаковку (У*)
    и «Смесь газ», срезаем префиксы (С*/П*/Б*/...), суммируем количества
    одинакового сырья и сортируем по убыванию (основной ингредиент первым),
    дубли по нормализованному имени схлопываем.
    """
    agg = {}  # normalized_name -> [display_name, total_amount]
    for pid, amount in _tree_leaves(root_pid, charts):
        p = products_by_id.get(pid)
        if not p:
            continue
        nm = p.get("name") or ""
        if _ingredient_excluded(nm):
            continue
        cn = _clean_ingredient(nm)
        if not cn:
            continue
        k = re.sub(r'\s+', ' ', cn).lower()
        if k not in agg:
            agg[k] = [cn, 0.0]
        agg[k][1] += (amount or 0.0)

    ordered = sorted(agg.values(), key=lambda x: -x[1])
    return ", ".join(name for name, _amt in ordered)


def _download_photo(url: str) -> tuple:
    if not url or not url.startswith("http"):
        return None, None
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return None, None
        content_type = resp.headers.get("Content-Type", "")
        if "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        elif "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        else:
            url_path = url.split("?")[0]
            ext = os.path.splitext(url_path)[1] or ".jpg"
        return resp.content, ext
    except Exception as e:
        logger.warning(f"Не удалось скачать фото {url}: {e}")
        return None, None


def _photo_url_changed(product, new_url: str) -> bool:
    if not product.photo:
        return True
    if not new_url:
        return False
    url_hash = hashlib.md5(new_url.encode()).hexdigest()[:8]
    current_name = os.path.basename(str(product.photo.name))
    return url_hash not in current_name


# ──────────────────────────────────────────────────────────────────────────────
# iikoCloud клиент
# ──────────────────────────────────────────────────────────────────────────────

class IikoCloudClient:
    BASE = "https://api-ru.iiko.services"

    def __init__(self, api_key: str, app_id: str = "", client_secret: str = ""):
        self.api_key = api_key
        self.app_id = app_id
        self.client_secret = client_secret
        self._token = None

    def _get_token(self) -> str:
        # Новая схема авторизации (iikoTransport): если задано зарегистрированное
        # приложение (appId + clientSecret) — используем эндпоинт /api/v2/access_token.
        # Старый /api/1/access_token отключается iiko (~29.08.2026), оставлен только
        # как запасной вариант, если приложение ещё не настроено.
        if self.app_id and self.client_secret:
            resp = _request_with_retry(
                "post", f"{self.BASE}/api/v2/access_token",
                json={
                    "apiLogin": self.api_key,
                    "appId": self.app_id,
                    "clientSecret": self.client_secret,
                }, timeout=20,
            )
        else:
            resp = _request_with_retry(
                "post", f"{self.BASE}/api/1/access_token",
                json={"apiLogin": self.api_key}, timeout=20,
            )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        return self._token

    def _headers(self) -> dict:
        if not self._token:
            self._get_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def get_nomenclature(self, org_id: str) -> dict:
        resp = _request_with_retry(
            "post", f"{self.BASE}/api/1/nomenclature",
            json={"organizationId": org_id, "startRevision": 0},
            headers=self._headers(), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_menu_by_id(self, menu_id: str, org_id: str) -> dict:
        resp = _request_with_retry(
            "post", f"{self.BASE}/api/2/menu/by_id",
            json={
                "externalMenuId": menu_id,
                "organizationIds": [org_id],
                "priceCategoryId": "00000000-0000-0000-0000-000000000000",
                "version": 2,
            },
            headers=self._headers(), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# iiko Server клиент
# ──────────────────────────────────────────────────────────────────────────────

class IikoServerClient:
    def __init__(self, server_url: str, login: str, password: str):
        self.base = server_url.rstrip("/")
        self.login = login
        self.password = password
        self._token = None

    def _get_token(self) -> str:
        resp = _request_with_retry(
            "get", f"{self.base}/api/auth",
            params={"login": self.login, "pass": self.password}, timeout=20,
        )
        resp.raise_for_status()
        self._token = resp.text.strip().strip('"')
        return self._token

    def _params(self, extra: dict = None) -> dict:
        if not self._token:
            self._get_token()
        p = {"key": self._token}
        if extra:
            p.update(extra)
        return p

    def logout(self):
        if self._token:
            try:
                requests.get(
                    f"{self.base}/api/auth/logout",
                    params={"key": self._token}, timeout=10,
                )
            except Exception:
                pass
            finally:
                self._token = None

    def get_products(self) -> list:
        resp = _request_with_retry(
            "get", f"{self.base}/api/v2/entities/products/list",
            params=self._params({"includeDeleted": "false"}), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_assembly_tree(self, product_id: str) -> list:
        """Полное дерево техкарт блюда (getTree) — список узлов assemblyCharts.
        В отличие от getPrepared, содержит и полуфабрикаты со списанием DIRECT,
        поэтому состав раскрывается до сырья без потерь. Пусто = карты нет."""
        from datetime import date
        resp = _request_with_retry(
            "get", f"{self.base}/api/v2/assemblyCharts/getTree",
            params=self._params({
                "date": date.today().strftime("%Y-%m-%d"),
                "productId": product_id,
            }), timeout=60,
        )
        resp.raise_for_status()
        if not resp.text.strip():
            return []
        return resp.json().get("assemblyCharts") or []

    def get_cost_report(self) -> dict:
        """OLAP-отчёт себестоимости за текущий месяц.
        Контрагент: 0Частное лицо Покупатель, тип транзакции: OUTGOING_INVOICE.
        Возвращает сырой JSON ответа iiko Server.
        """
        from datetime import date
        today = date.today()
        first_day = today.replace(day=1)
        if today.month == 12:
            next_first = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_first = today.replace(month=today.month + 1, day=1)

        body = {
            "reportType": "TRANSACTIONS",
            # GUID и артикул — надёжные ключи. Названия в складской номенклатуре
            # и в меню доставки расходятся, по ним часть позиций не находилась.
            "groupByRowFields": ["Product.Id", "Product.Num", "Product.Name"],
            "groupByColFields": [],
            # Amount.Out — количество в строке накладной; цена за единицу
            # считается как Sum.Incoming / Amount.Out (см. _parse_cost_report)
            "aggregateFields": ["Sum.Incoming", "Amount.Out"],
            "filters": {
                "DateTime.OperDayFilter": {
                    "filterType": "DateRange",
                    "from": first_day.strftime("%Y-%m-%dT00:00:00"),
                    "to": next_first.strftime("%Y-%m-%dT00:00:00"),
                    "includeLow": True,
                    "includeHigh": False,
                    "periodType": "CURRENT_MONTH",
                },
                "Product.ThirdParent": {
                    "filterType": "IncludeValues",
                    "values": ["ЗДОРОВОЕ ПИТАНИЕ"],
                },
                "TransactionType": {
                    "filterType": "IncludeValues",
                    "values": ["OUTGOING_INVOICE"],
                },
                "Counteragent.Name": {
                    "filterType": "IncludeValues",
                    "values": ["0Частное лицо Покупатель"],
                },
            },
        }

        resp = _request_with_retry(
            "post", f"{self.base}/api/v2/reports/olap",
            json=body,
            params=self._params(),
            headers={"Accept": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# Парсер внешнего меню
# ──────────────────────────────────────────────────────────────────────────────

def _extract_menu_items(menu_data: dict) -> dict:
    """
    Возвращает {product_uuid: {name, category_name, packing, weight,
                               photo_url, allergen_names, КБЖУ...}}
    allergen_names — список строк с именами аллергенов
    """
    result = {}

    def _parse_item(item: dict, cat_name: str):
        product_id = item.get("itemId") or item.get("id") or ""
        name = item.get("name") or ""
        if not product_id or not name:
            return

        # Блюдо может входить в несколько категорий внешнего меню —
        # копим все варианты, чтобы потом выбрать подходящую под SLOT_TYPES.
        if product_id in result:
            existing_cats = result[product_id]["category_names"]
            if cat_name and cat_name not in existing_cats:
                existing_cats.append(cat_name)
            return

        sizes = item.get("itemSizes") or []
        size = sizes[0] if sizes else {}

        nutr = size.get("nutritionPerHundredGrams") or {}
        if isinstance(nutr, list):
            nutr = nutr[0] if nutr else {}
        if not nutr:
            nutritions = size.get("nutritions") or []
            nutr = nutritions[0] if nutritions else {}

        weight_grams = _safe_float(size.get("portionWeightGrams"))

        kcal_100    = _safe_float(nutr.get("energy"))
        protein_100 = _safe_float(nutr.get("proteins"))
        fat_100     = _safe_float(nutr.get("fats"))
        carbs_100   = _safe_float(nutr.get("carbs"))
        kj_100      = round(kcal_100 * 4.184, 2) if kcal_100 is not None else None

        def per_serving(val):
            if val is not None and weight_grams:
                return round(val * weight_grams / 100, 2)
            return None

        photo_url = (
            size.get("buttonImageUrl")
            or item.get("buttonImageUrl")
            or ""
        )

        # Артикул блюда из внешнего меню iiko (короткий код)
        article = (
            item.get("sku")
            or size.get("sku")
            or item.get("code")
            or size.get("code")
            or ""
        )
        article = str(article).strip()

        # Аллергены — берём из item.allergens
        # Формат: [{id, code, name, isDeleted}, ...]
        allergen_names = []
        for a in item.get("allergens") or []:
            a_name = a.get("name") or ""
            a_deleted = str(a.get("isDeleted", "false")).lower()
            if a_name and a_deleted != "true":
                allergen_names.append(a_name.strip())

        result[product_id] = {
            "name":           name,
            "category_name":  cat_name,
            "category_names": [cat_name] if cat_name else [],
            "article":        article,
            "packing":        item.get("measureUnit") or "",
            "weight":         weight_grams,
            "photo_url":      photo_url,
            "allergen_names": allergen_names,  # список имён аллергенов
            "kcal":           kcal_100,
            "protein":        protein_100,
            "fat":            fat_100,
            "carbs":          carbs_100,
            "kj_100":         kj_100,
            "kcal_s":         per_serving(kcal_100),
            "protein_s":      per_serving(protein_100),
            "fat_s":          per_serving(fat_100),
            "carbs_s":        per_serving(carbs_100),
            "kj_s":           per_serving(kj_100),
        }

    def walk_categories(categories: list, parent_name: str = ""):
        for cat in categories or []:
            cat_name = cat.get("name") or parent_name or ""
            walk_categories(cat.get("childCategories") or [], cat_name)
            for item in cat.get("items") or []:
                _parse_item(item, cat_name)

    walk_categories(menu_data.get("itemCategories") or [])
    if not result:
        for pcat in menu_data.get("productCategories") or []:
            cat_name = pcat.get("name") or ""
            for item in pcat.get("items") or []:
                _parse_item(item, cat_name)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Парсер OLAP-отчёта себестоимости
# ──────────────────────────────────────────────────────────────────────────────

def _norm_name(s) -> str:
    """Нормализует название блюда: схлопывает пробелы, нижний регистр."""
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower()


def _norm_name_nosuffix(s) -> str:
    """То же + убирает хвостовой суффикс в скобках, напр. '(1порц)', '(3шт)'."""
    s = _norm_name(s)
    return re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()


def _parse_cost_report(report_data: dict) -> dict:
    """Разбирает OLAP-отчёт себестоимости в три индекса: по GUID, по артикулу
    и по названию — {'by_id': {...}, 'by_num': {...}, 'by_name': {...}}.

    Sum.Incoming — сумма по строке расходной накладной, Amount.Out — количество
    в ней; себестоимость единицы = сумма / количество. Строки с нулевым
    количеством пропускаем — цену из них не вывести.
    """
    index = {"by_id": {}, "by_num": {}, "by_name": {}}
    rows = report_data.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return index

    for row in rows:
        try:
            total = float(row.get("Sum.Incoming") or 0)
            amount = float(row.get("Amount.Out") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        unit = total / amount

        product_id = str(row.get("Product.Id") or "").strip()
        num = str(row.get("Product.Num") or "").strip()
        name = str(row.get("Product.Name") or "").strip()
        if product_id:
            index["by_id"].setdefault(product_id, unit)
        if num:
            index["by_num"].setdefault(num, unit)
        if name:
            index["by_name"].setdefault(_norm_name(name), unit)
            index["by_name"].setdefault(_norm_name_nosuffix(name), unit)
    return index


def _lookup_cost(index: dict, iiko_id: str, article: str, name: str):
    """Ищет себестоимость по самому надёжному ключу: сначала GUID, затем
    артикул и только потом название. Названия в складской номенклатуре и в
    меню доставки совпадают не всегда — по ним часть позиций терялась."""
    if not index:
        return None
    if iiko_id:
        hit = index["by_id"].get(str(iiko_id).strip())
        if hit is not None:
            return hit
    if article:
        hit = index["by_num"].get(str(article).strip())
        if hit is not None:
            return hit
    if name:
        hit = index["by_name"].get(_norm_name(name))
        if hit is None:
            hit = index["by_name"].get(_norm_name_nosuffix(name))
        return hit
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Главная функция синхронизации
# ──────────────────────────────────────────────────────────────────────────────

def sync_products_from_iiko(
    cloud_api_key: str,
    org_id: str,
    external_menu_id: str,
    server_url: str = "",
    server_login: str = "",
    server_password: str = "",
    cloud_app_id: str = "",
    cloud_client_secret: str = "",
) -> dict:
    global _last_sync_time

    now_ts = time.time()
    elapsed = now_ts - _last_sync_time
    if elapsed < MIN_SYNC_INTERVAL:
        wait_left = int(MIN_SYNC_INTERVAL - elapsed)
        return {
            "created": 0, "updated": 0, "skipped": 0, "deleted": 0,
            "errors": [f"Синхронизация запущена слишком часто. Подождите ещё {wait_left} сек."]
        }

    from .models import Product, MealCategory, Allergen

    result = {
        "created": 0, "updated": 0, "skipped": 0,
        "deleted": 0, "unchanged": 0, "errors": []
    }

    cloud = IikoCloudClient(cloud_api_key, cloud_app_id, cloud_client_secret)

    # ── Шаг 1: Внешнее меню ──────────────────────────────────────────────────
    try:
        menu_data = cloud.get_menu_by_id(external_menu_id, org_id)
    except Exception as e:
        result["errors"].append(f"iikoCloud menu: {e}")
        return result

    menu_map = _extract_menu_items(menu_data)
    if not menu_map:
        result["errors"].append("iikoCloud: блюд в меню не найдено.")
        return result

    logger.info(f"iikoCloud menu: {len(menu_map)} блюд")

    # Диагностика: какие категории реально приходят из iiko и совпадают ли с SLOT_TYPES
    all_cat_names = {}
    for info in menu_map.values():
        for cn in info.get("category_names") or []:
            if cn:
                all_cat_names[cn] = all_cat_names.get(cn, 0) + 1
    for cn, cnt in sorted(all_cat_names.items()):
        matched = _SLOT_LABEL_TO_KEY_NORM.get(_normalize_label(cn))
        codes = " ".join(f"U+{ord(c):04X}" for c in cn if not c.isalnum() and not c.isspace())
        logger.info(
            f"iiko категория: '{cn}' (символы: {codes or '-'}) — блюд: {cnt} "
            f"— match: {matched or 'НЕТ'}"
        )

    # Диагностика артикулов из меню
    with_article = sum(1 for i in menu_map.values() if i.get("article"))
    sample = [(i.get("article"), i.get("name")) for i in menu_map.values() if i.get("article")][:5]
    logger.info(f"iiko артикулы из меню: {with_article}/{len(menu_map)} блюд. Примеры: {sample}")

    # ── Шаг 2: Номенклатура — артикулы ───────────────────────────────────────
    uuid_to_sku = {}
    try:
        nom = cloud.get_nomenclature(org_id)
        for prod in nom.get("products") or []:
            pid = prod.get("id") or ""
            num = prod.get("num") or prod.get("code") or ""
            if pid and num:
                uuid_to_sku[pid] = str(num).strip()
        logger.info(f"Nomenclature: {len(uuid_to_sku)} артикулов")
    except Exception as e:
        logger.warning(f"Номенклатура: {e}")
        result["errors"].append(f"Nomenclature: {e}")

    # ── Шаг 3: iiko Server — состав + себестоимость ──────────────────────────
    server_composition = {}
    cost_index = {}
    if server_url and server_login:
        server = None
        try:
            server = IikoServerClient(server_url, server_login, server_password)

            # Состав блюд — из технологических карт (getTree, раскрытых до сырья).
            # Фолбэк — description продукта. Запросы техкарт независимы и I/O-bound,
            # поэтому тянем их пулом потоков: последовательно ~269 запросов не
            # укладываются в таймаут веб-сервера.
            server_products = server.get_products()
            products_by_id = {sp.get("id"): sp for sp in server_products if sp.get("id")}
            dish_ids = [pid for pid in menu_map if pid in products_by_id]

            def _fetch_composition(pid):
                try:
                    charts = server.get_assembly_tree(pid)
                    return pid, _composition_from_tree(pid, charts, products_by_id)
                except Exception as e:
                    logger.debug(f"Техкарта {menu_map.get(pid, {}).get('name', pid)}: {e}")
                    return pid, ""

            comp_from_chart = 0
            with ThreadPoolExecutor(max_workers=COMPOSITION_WORKERS) as ex:
                for pid, comp in ex.map(_fetch_composition, dish_ids):
                    if comp:
                        comp_from_chart += 1
                    else:
                        sp = products_by_id.get(pid)
                        comp = _parse_description(sp.get("description")) if sp else ""
                    if comp:
                        server_composition[pid] = comp
            logger.info(
                f"iiko Server: состав для {len(server_composition)} блюд "
                f"(из техкарт: {comp_from_chart}, из description: "
                f"{len(server_composition) - comp_from_chart})"
            )

            # Себестоимость из OLAP-отчёта
            try:
                raw_report = server.get_cost_report()
                cost_index = _parse_cost_report(raw_report)
                logger.info(
                    "OLAP себестоимость: %d позиций (по GUID %d, по артикулу %d)"
                    % (len(cost_index["by_id"]), len(cost_index["by_id"]),
                       len(cost_index["by_num"]))
                )
            except Exception as e:
                logger.warning(f"OLAP отчёт себестоимости: {e}")
                result["errors"].append(f"OLAP себестоимость: {e}")

            server.logout()
        except Exception as e:
            logger.warning(f"iiko Server: {e}")
            result["errors"].append(f"iiko Server: {e}")
            if server:
                try:
                    server.logout()
                except Exception:
                    pass

    # ── Шаг 4: Артикулы ──────────────────────────────────────────────────────
    iiko_skus_in_menu = set()
    iiko_uuid_to_sku  = {}
    for uuid in menu_map:
        sku = uuid_to_sku.get(uuid, uuid)
        iiko_skus_in_menu.add(sku)
        iiko_uuid_to_sku[uuid] = sku

    # ── Шаг 5: Удаление ──────────────────────────────────────────────────────
    # Защита: блюда, используемые в рационах или подгруппах на замену, НЕ удаляем,
    # даже если их артикул пропал из меню iiko.
    from .models import RationSlot as _RationSlot, SwapItem as _SwapItem
    used_product_ids = set(
        _RationSlot.objects.filter(product__isnull=False).values_list("product_id", flat=True)
    ) | set(
        _SwapItem.objects.values_list("product_id", flat=True)
    )

    # АВТО-УДАЛЕНИЕ ОТКЛЮЧЕНО.
    # Раньше блюда, пропавшие из меню iiko, удалялись автоматически — это приводило
    # к потере блюд в каталоге, обнулению слотов рационов и удалению позиций на замену
    # (например, когда в iiko пересоздавали подгруппы и у блюд менялись ID).
    # Теперь синхронизация НИЧЕГО не удаляет — только фиксирует «кандидатов» в лог.
    # Удалять ненужные блюда можно вручную через админку.
    delete_candidates = Product.objects.filter(
        iiko_sku__isnull=False
    ).exclude(iiko_sku__in=iiko_skus_in_menu).exclude(pk__in=used_product_ids)

    cand_count = delete_candidates.count()
    if cand_count > 0:
        names = list(delete_candidates.values_list("name", flat=True))
        logger.warning(
            f"Кандидаты на удаление (НЕ удалены, авто-удаление отключено): "
            f"{cand_count}: {names}"
        )
        result["delete_candidates"] = cand_count
    result["deleted"] = 0

    # ── Шаг 6: Предзагружаем существующие продукты ───────────────────────────
    existing_by_sku = {
        p.iiko_sku: p
        for p in Product.objects.filter(iiko_sku__in=iiko_skus_in_menu)
    }
    existing_by_uuid = {
        p.iiko_id: p
        for p in Product.objects.filter(
            iiko_id__in=set(menu_map.keys())
        ).exclude(iiko_sku__isnull=False)
    }

    # Индекс по АРТИКУЛУ — устойчивое сопоставление, даже если внутренний код iiko
    # поменялся (напр. блюдо пересоздали в новой подгруппе с тем же артикулом).
    # Берём только артикулы, уникальные И в меню, И в базе — чтобы не перепутать блюда.
    from collections import Counter as _Counter
    _menu_art_counts = _Counter(
        (info.get("article") or "").strip()
        for info in menu_map.values()
        if (info.get("article") or "").strip()
    )
    _unique_menu_articles = {a for a, n in _menu_art_counts.items() if n == 1}
    existing_by_article = {}
    _dup_articles = set()
    if _unique_menu_articles:
        for p in Product.objects.filter(article__in=_unique_menu_articles):
            a = (p.article or "").strip()
            if not a:
                continue
            if a in existing_by_article:
                _dup_articles.add(a)          # артикул задвоен в базе — не сопоставляем по нему
            else:
                existing_by_article[a] = p
        for a in _dup_articles:
            existing_by_article.pop(a, None)

    article_matched = 0

    now = dj_timezone.now()

    cost_matched = 0
    cost_unmatched = []

    # Сопоставление категорий: код + редактируемое из админки
    label_to_key = _build_label_to_key()

    # ── Шаг 7: Создаём / обновляем ───────────────────────────────────────────
    for uuid, menu_info in menu_map.items():
        sku = iiko_uuid_to_sku.get(uuid, uuid)

        try:
            # 1) по артикулу (стабильно), 2) по коду iiko (запасной вариант)
            _art = (menu_info.get("article") or "").strip()
            product = None
            if _art and _art in existing_by_article:
                product = existing_by_article[_art]
                article_matched += 1
            if product is None:
                product = existing_by_sku.get(sku) or existing_by_uuid.get(uuid)
            is_new = product is None

            cat_display, matched_slot_key = _pick_category(menu_info, label_to_key)

            # Артикул: сначала из меню, иначе из номенклатуры (num), но НЕ uuid
            article = menu_info.get("article") or ""
            if not article:
                nom_num = uuid_to_sku.get(uuid)
                if nom_num and nom_num != uuid:
                    article = nom_num

            new_fields = {
                "name":           menu_info["name"],
                "article":        article,
                "iiko_category":  cat_display,
                "iiko_sku":       sku,
                "iiko_id":        uuid,
            }
            if menu_info.get("packing"):
                new_fields["packing"] = menu_info["packing"]
            if menu_info.get("weight") is not None:
                new_fields["net_weight"] = menu_info["weight"] / 1000
            for src, dst in [
                ("kcal",      "kcal_per_100"),
                ("protein",   "protein"),
                ("fat",       "fat"),
                ("carbs",     "carbs"),
                ("kj_100",    "kj_per_100"),
                ("kcal_s",    "kcal_per_serving"),
                ("protein_s", "protein_per_serving"),
                ("fat_s",     "fat_per_serving"),
                ("carbs_s",   "carbs_per_serving"),
                ("kj_s",      "kj_per_serving"),
            ]:
                if menu_info.get(src) is not None:
                    new_fields[dst] = menu_info[src]
            if uuid in server_composition:
                new_fields["composition"] = server_composition[uuid]

            # Себестоимость: GUID → артикул → название
            if cost_index:
                product_name = menu_info["name"]
                cost_val = _lookup_cost(cost_index, uuid, article, product_name)
                if cost_val is not None:
                    # Decimal, а не float: поле DecimalField, и цена продажи
                    # считается в Decimal — смешение типов ломает сохранение
                    new_fields["cost"] = Decimal(str(round(cost_val, 2)))
                    cost_matched += 1
                else:
                    cost_unmatched.append(product_name)

            if is_new:
                new_fields["iiko_synced_at"] = now
                product = Product.objects.create(**new_fields)
                result["created"] += 1
            else:
                changed, changed_fields = _fields_changed(product, new_fields)
                if changed:
                    for k, v in new_fields.items():
                        setattr(product, k, v)
                    product.iiko_synced_at = now
                    product.save()
                    result["updated"] += 1
                    logger.debug(f"Обновлён '{menu_info['name']}': {changed_fields}")
                else:
                    result["unchanged"] += 1

            # ── Фото ─────────────────────────────────────────────────────────
            photo_url = menu_info.get("photo_url", "")
            if photo_url and _photo_url_changed(product, photo_url):
                photo_data, ext = _download_photo(photo_url)
                if photo_data:
                    url_hash = hashlib.md5(photo_url.encode()).hexdigest()[:8]
                    filename = f"iiko_{sku}_{url_hash}{ext}"
                    if product.photo:
                        try:
                            product.photo.delete(save=False)
                        except Exception:
                            pass
                    product.photo.save(filename, ContentFile(photo_data), save=True)

            # ── Аллергены ─────────────────────────────────────────────────────
            # get_or_create каждого аллергена по имени, затем синхронизируем M2M
            allergen_names = menu_info.get("allergen_names") or []
            if allergen_names:
                allergen_objs = []
                for a_name in allergen_names:
                    allergen, _ = Allergen.objects.get_or_create(name=a_name)
                    allergen_objs.append(allergen)
                # Полная замена — устанавливаем ровно тех что пришли из iiko
                product.allergens.set(allergen_objs)
            else:
                # Если в iiko аллергенов нет — очищаем
                product.allergens.clear()

            # ── Категория ─────────────────────────────────────────────────────
            if matched_slot_key:
                try:
                    meal_cat = MealCategory.objects.get(key=matched_slot_key)
                    product.meal_categories.set([meal_cat])
                except MealCategory.DoesNotExist:
                    logger.debug(f"MealCategory '{matched_slot_key}' не найдена в БД")

        except Exception as e:
            msg = f"'{menu_info.get('name', uuid)}': {e}"
            logger.error(f"Ошибка: {msg}")
            result["errors"].append(msg)
            result["skipped"] += 1

    _last_sync_time = time.time()

    if cost_index:
        logger.info(
            f"Себестоимость: сопоставлено {cost_matched}, "
            f"не найдено {len(cost_unmatched)}. "
            f"Без цены: {cost_unmatched[:15]}"
        )

    logger.info(f"Сопоставлено по артикулу: {article_matched} блюд")
    logger.info(
        f"Готово — создано: {result['created']}, "
        f"обновлено: {result['updated']}, "
        f"без изменений: {result['unchanged']}, "
        f"удалено: {result['deleted']}, "
        f"пропущено: {result['skipped']}"
    )
    return result
```

## Приложение B. Словарь ингредиентов и чистка состава (`ingredient_aliases.py`)

Переносить файлом целиком, без изменений.

```python
"""Справочник ингредиентов: сырое название из iiko → название для состава.

Собран разово по всем 309 названиям (правила + Claude), вычитан пользователем
15.08.2026. Ингредиенты, которых здесь нет, попадают в состав как есть —
посмотреть такие можно командой `manage.py unknown_ingredients`.

Правила, по которым собирался справочник:
  • убираются числа, проценты, единицы (л/шт/кг/г/мл), сорта (в/с, 1с),
    складские пометки («фудзавод», «дорогая», «в ассортименте», «неисп»);
  • слово-категория в начале убирается, только если без него понятно:
    «Специя Перец черный горошек» → «Перец черный», но «Соус терияки» остаётся;
  • уточнения, меняющие продукт, сохраняются («Мука пшеничная цельнозерновая»),
    помол/цвет/поставщик — убираются («Соль мелкая» → «Соль»).
"""

import re

# Ингредиенты в составе разделены «запятая + пробел». Внутри самих названий
# такой пары нет (десятичные запятые идут без пробела: «Молоко 3,2%»),
# поэтому разбор однозначный.
_SPLIT_RE = re.compile(r",\s")


def split_ingredients(raw: str) -> list:
    """Разбирает строку состава на отдельные ингредиенты."""
    if not raw:
        return []
    return [part.strip() for part in _SPLIT_RE.split(raw) if part.strip()]


def clean_composition(raw: str) -> str:
    """Состав для показа: подменяет названия по справочнику и убирает дубли,
    появившиеся после подмены («Соль мелкая» + «Соль крупная» → одна «Соль»).

    Порядок сохраняется — в исходной строке ингредиенты идут по убыванию
    массы, и это важно для этикетки. Незнакомое название остаётся как есть:
    ингредиент не должен исчезнуть из состава ни при каких обстоятельствах.
    """
    seen = set()
    result = []
    for part in split_ingredients(raw):
        name = INGREDIENT_ALIASES.get(part, part)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return ", ".join(result)


# Все 309 названий, встречавшихся в составах на 15.08.2026 — включая те, что
# менять не нужно: справочник помнит, что они уже просмотрены, и команда
# unknown_ingredients показывает только по-настоящему новое сырьё.
# сырое название: чистое название
INGREDIENT_ALIASES = {
    "Smartex (для эмульсии)": "Smartex",
    "Авокадо": "Авокадо",   # без изменений
    "Ананас свежий": "Ананас",
    "Ананас СМ": "Ананас",
    "Апельсин": "Апельсин",   # без изменений
    "Ароматизатор ваниль": "Ваниль",
    "Бабы Эдамаме": "Бобы Эдамаме",
    "Баклажан": "Баклажан",   # без изменений
    "Банан": "Банан",   # без изменений
    "Бедро индейки": "Бедро индейки",   # без изменений
    "Ванилин порошок": "Ванилин",
    "Ветчина индейка": "Ветчина индейка",   # без изменений
    "Ветчина с говядиной": "Ветчина с говядиной",   # без изменений
    "Вода Боржоми (жб) 330 мл": "Вода Боржоми",
    "Вода Боржоми (пластик) 500 мл": "Вода Боржоми",
    "Вода Боржоми (стекло) 330 мл": "Вода Боржоми",
    "Вода Боржоми (стекло) 500 мл": "Вода Боржоми",
    "Вода минеральная Сары-Агаш": "Вода минеральная",
    "Говяжья вырезка": "Говяжья вырезка",   # без изменений
    "Горох": "Горох",   # без изменений
    "Горошек зеленый СМ": "Горошек зеленый",
    "Горчица": "Горчица",   # без изменений
    "Горчица зерновая": "Горчица зерновая",   # без изменений
    "Гранат": "Гранат",   # без изменений
    "Грейпфрут": "Грейпфрут",   # без изменений
    "Грибы вешенки": "Вешенки",
    "Грибы шампиньоны": "Шампиньоны",
    "Груша": "Груша",   # без изменений
    "Дрожжи сухие": "Дрожжи сухие",   # без изменений
    "Жая конина": "Жая конина",   # без изменений
    "Желатин": "Желатин",   # без изменений
    "Жир (говядина)": "Жир говяжий",
    "Закваска Бостер": "Закваска Бостер",   # без изменений
    "Заменитель сахара Стевия": "Заменитель сахара Стевия",   # без изменений
    "Заменитель сахара Эритрит": "Эритрит",
    "Зелень Базилик": "Базилик",
    "Зелень Кинза": "Кинза",
    "Зелень Лук зеленый": "Лук зеленый",
    "Зелень Мята": "Мята",
    "Зелень Петрушка": "Петрушка",
    "Зелень Розмарин": "Розмарин",
    "Зелень Руккола": "Руккола",
    "Зелень Сельдерей (зелень)": "Сельдерей",
    "Зелень Сельдерей (стебель)": "Сельдерей (стебель)",
    "Зелень Тимьян": "Тимьян",
    "Зелень Укроп": "Укроп",
    "Изюм желтый": "Изюм",
    "Имбирная паста": "Имбирная паста",   # без изменений
    "Имбирь корень": "Имбирь",
    "Йогурт": "Йогурт",   # без изменений
    "Йогурт греческий": "Йогурт греческий",   # без изменений
    "Кабачки": "Кабачки",   # без изменений
    "Казы сырые": "Казы",
    "Какао порошок": "Какао порошок",   # без изменений
    "Какао темная пудра 22/24": "Какао-пудра",
    "Каперсы консервированные": "Каперсы консервированные",   # без изменений
    "Капуста басай": "Капуста басай",   # без изменений
    "Капуста басай пекинская листья": "Капуста пекинская",
    "Капуста белокочанная": "Капуста белокочанная",   # без изменений
    "Капуста Брокколи": "Брокколи",
    "Капуста Брокколи СМ": "Капуста брокколи",
    "Капуста квашеная": "Капуста квашеная",   # без изменений
    "Капуста фиолет": "Капуста",
    "Капуста цветная": "Капуста цветная",   # без изменений
    "Капуста цветная СМ": "Капуста цветная",
    "Картофель": "Картофель",   # без изменений
    "Кефир 2.5% л": "Кефир",
    "Киви": "Киви",   # без изменений
    "Клюква сушеная": "Клюква сушеная",   # без изменений
    "Кнорр куриный": "Кнорр куриный",   # без изменений
    "Кнорр овощной": "Кнорр овощной",   # без изменений
    "Концентрат лимонный": "Сок лимона",
    "Концентрат лимонный л (сок лимона)": "Сок лимона",
    "Корица порошок": "Корица",
    "Кости говядина": "Кости говядина",   # без изменений
    "Кости куриные": "Кости куриные",   # без изменений
    "Крахмал бобовый": "Крахмал бобовый",   # без изменений
    "Крахмал картофельный": "Крахмал картофельный",   # без изменений
    "Крахмал кукурузный": "Крахмал кукурузный",   # без изменений
    "Креветки  кг": "Креветки",
    "Крем бальзамик л": "Крем бальзамик",
    "Крупа Булгур": "Булгур",
    "Крупа Гречка": "Гречка",
    "Крупа гречка зеленая": "Гречка зеленая",
    "Крупа Киноа": "Киноа",
    "Крупа Киноа черная": "Киноа черная",
    "Крупа кукурузная": "Кукурузная крупа",
    "Крупа Кускус": "Кускус",
    "Крупа манная": "Манная крупа",
    "Крупа Овсянка": "Овсянка",
    "Крупа Овсянка геркулес": "Овсянка геркулес",
    "Крупа Перловка": "Перловка",
    "Крупа полба": "Полба",
    "Крупа Пшено": "Пшено",
    "Крупа ячневая": "Ячневая крупа",
    "Кукуруза консервир.": "Кукуруза консервированная",
    "Кунжут семена белый": "Кунжут",
    "Кунжут семена черный": "Кунжут черный",
    "Курага": "Курага",   # без изменений
    "Лайм": "Лайм",   # без изменений
    "Лапша гречневая": "Лапша гречневая",   # без изменений
    "Лапша Спагетти": "Спагетти",
    "Лапша Фунчоза картофельная": "Лапша Фунчоза картофельная",   # без изменений
    "Лапша Фунчоза рисовая": "Фунчоза",
    "Лимон": "Лимон",   # без изменений
    "Лист салата Романо": "Салат романо",
    "Листья для суши (нори)": "Нори",
    "Лук красный": "Лук",
    "Лук порей": "Лук порей",   # без изменений
    "Лук репчатый": "Лук репчатый",   # без изменений
    "Майонез": "Майонез",   # без изменений
    "Мак": "Мак",   # без изменений
    "Макароны Пенне": "Макароны Пенне",   # без изменений
    "Макароны Пенне 5 Злаков": "Макароны Пенне 5 злаков",
    "Макароны Пенне цельнозерновое": "Макароны Пенне цельнозерновые",
    "Макароны Спираль ( фузилле)": "Макароны Спираль",
    "Манго СМ": "Манго",
    "Маргарин 65%": "Маргарин",
    "Маргарин д/слоеного тесто ПРОИЗВОДСТВО": "Маргарин для слоеного теста",
    "Маслины неисп Б2,Б3": "Маслины",
    "Масло Гхи": "Масло Гхи",   # без изменений
    "Масло кукурузное л": "Масло кукурузное",
    "Масло кунжутное л": "Масло кунжутное",
    "Масло оливковое л": "Масло оливковое",
    "Масло растительное л": "Масло растительное",
    "Масло сливочное Закрома": "Масло сливочное",
    "Масло фритюрное л": "Масло фритюрное",
    "Мед": "Мед",   # без изменений
    "Миндальные слайсы": "Миндальные слайсы",   # без изменений
    "Молоко 3,2% л": "Молоко",
    "Молоко кокосовое": "Молоко кокосовое",   # без изменений
    "Молоко миндальное л": "Молоко миндальное",
    "Молоко сухое": "Молоко сухое",   # без изменений
    "Морковь желтая": "Морковь",
    "Морковь красная": "Морковь",
    "Мука 1 сорт": "Мука",
    "Мука в/с дешевле": "Мука пшеничная",
    "Мука в/с дорогая": "Мука",
    "Мука для пасты": "Мука для пасты",   # без изменений
    "Мука миндальная": "Мука миндальная",   # без изменений
    "Мука овсяная": "Мука овсяная",   # без изменений
    "Мука пшеничная цельнозерновая": "Мука пшеничная цельнозерновая",   # без изменений
    "Мука рисовая": "Мука рисовая",   # без изменений
    "Мясо Говядина мякоть": "Говядина мякоть",
    "Напиток к/м EXPONENTA HIGH-PRO 250 мл": "Напиток кисломолочный EXPONENTA HIGH-PRO",
    "Напиток к/м EXPONENTA HIGH-PRO клубника-арбуз 250 мл": "Напиток кисломолочный EXPONENTA HIGH-PRO клубника-арбуз",
    "Напиток к/м EXPONENTA HIGH-PRO кокос-миндаль 250 мл": "Напиток кисломолочный EXPONENTA HIGH-PRO кокос-миндаль",
    "Напиток к/м EXPONENTA HIGH-PRO лимонный чизкейк 250 мл": "Напиток кисломолочный EXPONENTA HIGH-PRO лимонный чизкейк",
    "Напиток к/м EXPONENTA HIGH-PRO черника-земляника 250 мл": "Напиток кисломолочный EXPONENTA HIGH-PRO черника-земляника",
    "Напиток к/м БЕЗЛАКТОЗНЫЙ EXPONENTA HIGH-PRO клубник-земляника 250 мл": "Напиток кисломолочный безлактозный EXPONENTA HIGH-PRO клубника-земляника",
    "Напиток к/м ОБЕЗЖИР.безлактоз EXPONENTA HIGH-PRO манго-какос 250 мл": "Напиток кисломолочный обезжиренный безлактозный EXPONENTA HIGH-PRO манго-кокос",
    "Напиток к/м ОБЕЗЖИРЕН.EXPONENTA HIGH-PRO малина-банан 250 мл": "Напиток кисломолочный обезжиренный EXPONENTA HIGH-PRO малина-банан",
    "Напиток к/м ОБЕЗЖИРЕН.EXPONENTA HIGH-PRO соленая карамель 250 мл": "Напиток кисломолочный обезжиренный EXPONENTA HIGH-PRO соленая карамель",
    "Начинка крем микс соленая карамель": "Начинка крем соленая карамель",
    "Нут": "Нут",   # без изменений
    "Огурцы": "Огурцы",   # без изменений
    "Огурцы маринованные": "Огурцы маринованные",   # без изменений
    "Окорочка без костей": "Окорочка без костей",   # без изменений
    "Окорочка копченная": "Окорочка копченые",
    "Оливки неисп Б2,Б3": "Оливки",
    "Оптиспайс \"Пф домашние пельмени\" (пищевая добавка)": "Оптиспайс",
    "Орех арахис дробленый": "Арахис",
    "Орех грецкий": "Орех грецкий",   # без изменений
    "Орех кедровый": "Орех кедровый",   # без изменений
    "Паста Арахисовая": "Паста арахисовая",
    "Паста Карри красный": "Паста карри красная",
    "Паста кунжутная(тахини)": "Паста кунжутная (тахини)",
    "Паста орзо": "Паста орзо",   # без изменений
    "Паста Том Ям": "Паста том ям",
    "Паста Томатная": "Паста томатная",
    "Паста трюфельная": "Паста трюфельная",   # без изменений
    "Паста шоколадная Nutella": "Паста шоколадная Nutella",   # без изменений
    "Перец болгарский желтый": "Перец болгарский",
    "Перец болгарский зеленый": "Перец болгарский",
    "Перец болгарский красный": "Перец болгарский",
    "Перец полугорький зеленый": "Перец полугорький",
    "Перец полугорький красный": "Перец полугорький",
    "Перец чили": "Перец чили",   # без изменений
    "Перец чили маринованный (халапеньо)": "Перец халапеньо маринованный",
    "Печень куриная": "Печень куриная",   # без изменений
    "Помидор вяленые": "Помидоры вяленые",
    "Помидор розовый": "Помидор",
    "Помидоры": "Помидоры",   # без изменений
    "Помидоры маринованные пилати": "Помидоры маринованные",
    "Помидоры черри": "Помидоры черри",   # без изменений
    "Приправа Дашида": "Дашида",
    "Приправа итальянские травы": "Итальянские травы",
    "Приправа яними/кристаллики": "Приправа яними",
    "Пюре Малина": "Пюре малина",
    "Пюре Манго": "Пюре манго",
    "Пюре Маракуйя": "Пюре маракуйя",
    "Пюре Юдзу": "Пюре юдзу",
    "Разрыхлитель теста": "Разрыхлитель теста",   # без изменений
    "Редиска": "Редиска",   # без изменений
    "Рис баракат": "Рис",
    "Рис бурый": "Рис бурый",   # без изменений
    "Рыба Морской язык": "Морской язык",
    "Рыба Судак СМ": "Судак",
    "Рыба Форель без кожуры": "Форель без кожуры",
    "Салат Айсберг": "Салат Айсберг",   # без изменений
    "Салат Радичио": "Салат Радичио",   # без изменений
    "Салат Фризе": "Салат фризе",
    "Сахар ванильный": "Сахар ванильный",   # без изменений
    "Сахар песок": "Сахар",
    "Свекла": "Свекла",   # без изменений
    "Семга филе без кожуры": "Семга филе без кожуры",   # без изменений
    "Семена льна": "Семена льна",   # без изменений
    "Семена Чиа": "Семена чиа",
    "Семечки подсолнечника очищ": "Семечки подсолнечника",
    "Семечки тыквы очищенные": "Семечки тыквы",
    "Сироп без сахара в ассортименте": "Сироп без сахара",
    "Сироп Глюкоза": "Сироп глюкозы",
    "Сироп Гренадин л": "Сироп гренадин",
    "Сироп топинамбура": "Сироп топинамбура",   # без изменений
    "Сливки 33% л": "Сливки",
    "Сливки д/производства л": "Сливки",
    "Смесь ВипКрем": "Смесь ВипКрем",   # без изменений
    "Сметана 20%": "Сметана",
    "Соевый соус DunKan / Kikkoman л": "Соевый соус",
    "Соль крупная": "Соль",
    "Соль мелкая": "Соль",
    "Соус Ворчестер л": "Соус Ворчестер",
    "Соус Горчичный HEINZ кг": "Соус горчичный",
    "Соус горчичный изи": "Соус горчичный",
    "Соус Деми Глас ( сухая смесь)": "Соус Деми Глас",
    "Соус ореховая": "Соус ореховый",
    "Соус Релиш изи": "Соус релиш",
    "Соус рыбный л": "Соус рыбный",
    "Соус свит чили кг": "Соус свит чили",
    "Соус соевый в ассортименте л": "Соус соевый",
    "Соус соевый Китай для лагмана 5л": "Соус соевый",
    "Соус соевый Лаушу (лагман)": "Соус соевый",
    "Соус терияки л": "Соус терияки",
    "Соус Тонкацу": "Соус тонкацу",
    "Соус устричный л": "Соус устричный",
    "Соус чили манго изи": "Соус чили манго",
    "Соус Шрирача": "Соус Шрирача",   # без изменений
    "Специи Гарам масала": "Гарам масала",
    "Специя Бадьян (звездочка)": "Бадьян",
    "Специя Базилик сухой": "Базилик сухой",
    "Специя Жидкий дым": "Жидкий дым",
    "Специя Зира": "Зира",
    "Специя Кардамон": "Кардамон",
    "Специя Кориандр/Кинза горошек": "Кориандр",
    "Специя Куркума молотая": "Куркума",
    "Специя Лавровый лист": "Лавровый лист",
    "Специя Орегано сухой": "Орегано",
    "Специя Перец паприка острый": "Перец паприка острый",
    "Специя Перец паприка острый (корея)": "Перец паприка острый",
    "Специя Перец паприка сладкий": "Паприка сладкая",
    "Специя Перец черный горошек": "Перец черный",
    "Специя Сумах": "Сумах",
    "Специя Тимьян сухой": "Тимьян",
    "Специя Фахита": "Фахита",
    "Специя Хмели сунели": "Хмели-сунели",
    "Специя Чеснок гранулированный": "Чеснок гранулированный",
    "Сухари Аксай д/заморозки": "Сухари",
    "Сухари панировочные": "Сухари панировочные",   # без изменений
    "Сыр Адыгейский (Klimenko)": "Сыр Адыгейский",
    "Сыр Креметте (Хохланд)": "Сыр Креметте",
    "Сыр Моцарелла": "Сыр Моцарелла",   # без изменений
    "Сыр Пармезан": "Сыр Пармезан",   # без изменений
    "Сыр Пармезан Джугас": "Сыр Пармезан",
    "Сыр плавленый сливочный": "Сыр плавленый сливочный",   # без изменений
    "Сыр сметанковый": "Сыр сметанковый",   # без изменений
    "Сыр творожный с зеленью д/произ": "Сыр творожный с зеленью",
    "Сыр Фетакса": "Сыр Фетакса",   # без изменений
    "Творог 18%": "Творог",
    "Творог 9% (president)": "Творог",
    "Текстурат": "Текстурат",   # без изменений
    "Тортилья": "Тортилья",   # без изменений
    "Тунец консервированный": "Тунец консервированный",   # без изменений
    "Тыква": "Тыква",   # без изменений
    "Уксус 70% л": "Уксус",
    "Уксус винный л": "Уксус винный",
    "Уксус рисовый л": "Уксус рисовый",
    "Улучшитель хлебопекарный S500 МШК10": "Улучшитель хлебопекарный S500",
    "Улучшитель хлебопекарный Мажимикс": "Улучшитель хлебопекарный Мажимикс",   # без изменений
    "Фарш говядина Казбиф": "Фарш говядина",
    "Фасоль Белая": "Фасоль белая",
    "Фасоль консервированная": "Фасоль консервированная",   # без изменений
    "Фасоль Красная": "Фасоль красная",
    "Фасоль стручковая СМ": "Фасоль стручковая",
    "Филе грудка индейки": "Филе грудки индейки",
    "Филе куриное": "Филе куриное",   # без изменений
    "Филе утиное": "Филе утиное",   # без изменений
    "Финики": "Финики",   # без изменений
    "Финики королевский": "Финики",
    "Чернослив": "Чернослив",   # без изменений
    "Чеснок": "Чеснок",   # без изменений
    "Чечевица красная": "Чечевица красная",   # без изменений
    "Шнит лук(сибулет)": "Шнит-лук",
    "Шоколад горький 71,5%": "Шоколад горький",
    "Шоколадная глазурь капля": "Шоколадная глазурь",
    "Шпажки": "Шпажки",   # без изменений
    "Шпинат": "Шпинат",   # без изменений
    "Шпинат СМ": "Шпинат",
    "Яблоки": "Яблоки",   # без изменений
    "Ягода Брусника СМ": "Брусника",
    "Ягода Голубика свежая": "Голубика",
    "Ягода Клубника свежая": "Клубника",
    "Ягода Клубника СМ": "Клубника",
    "Ягода Клюква СМ": "Клюква",
    "Ягода Малина СМ (экстра)": "Малина",
    "Ягода Смородина СМ": "Смородина",
    "Ягода Черника СМ": "Черника",
    "Язык говядина": "Язык говяжий",
    "Яйцо особое шт": "Яйцо",
    "Яйцо фудзавод шт": "Яйцо",
}
```

Шаблон команды поиска новых ингредиентов (адаптировать под свою модель):

```python
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
```
