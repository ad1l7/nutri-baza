# Olive nutri-baza — API выгрузки для общей базы

Платформа **nutri-baza** (`olive-nutri-baza.kz`) — каталог блюд фудзавода Olive,
синхронизированный с iiko, плюс калоражи, рационы и блюда на замену.
Этот API отдаёт **всю базу платформы одним JSON** — чтобы раз в сутки забирать
её в общую базу Supabase.

---

## 1. Запрос

```
GET https://olive-nutri-baza.kz/api/export/
Authorization: Bearer <EXPORT_API_TOKEN>
```

Токен выдаётся отдельно (не храните его в репозитории — только в секретах).

```bash
curl -H "Authorization: Bearer $OLIVE_EXPORT_TOKEN" https://olive-nutri-baza.kz/api/export/
```

| Код | Значение |
|---|---|
| `200` | всё хорошо, JSON ниже |
| `401` | нет заголовка или неверный токен |
| `405` | метод не GET |
| `503` | выгрузка выключена на стороне платформы (токен не настроен) |

- Ответ ~1 МБ (сентябрь 2026: 319 блюд, 274 рациона, ~2000 слотов), отдаётся за доли секунды.
- Кодировка UTF-8, кириллица без экранирования.
- Все даты — ISO 8601 в **UTC** (`2026-07-18T11:04:15.630118+00:00`).
- Денежные поля — **тенге**, вес — **граммы**, КБЖУ — граммы / ккал / кДж.
- Лимитов нет, но запрашивать чаще раза в час смысла нет.

**Когда забирать.** Раз в сутки, ночью, например в 03:00 по Алматы (22:00 UTC).
Данные меняются днём: синхронизация с iiko запускается вручную, рационы
редактируют сотрудники.

---

## 2. Формат ответа

Это **полный снимок**, а не изменения за день. Верхний уровень:

```json
{
  "schema_version": 1,
  "source": "olive-nutri-baza",
  "generated_at": "2026-09-15T22:00:01.123456+00:00",
  "counts": { "products": 271, "rations": 5, "...": 0 },

  "meal_categories":        [ ... ],
  "meal_times":             [ ... ],
  "products":               [ ... ],
  "calorie_categories":     [ ... ],
  "calorie_category_meals": [ ... ],
  "ration_groups":          [ ... ],
  "rations":                [ ... ],
  "ration_slots":           [ ... ],
  "swap_groups":            [ ... ],
  "swap_items":             [ ... ],
  "materials":              [ ... ],
  "iiko_category_map":      [ ... ]
}
```

Каждая таблица — плоский массив строк, связи — по `id` (как внешние ключи).
`id` — первичные ключи платформы, **стабильные**: у записи не меняются.

`schema_version` поднимается при несовместимом изменении формата (переименование
или удаление поля). Новые поля могут добавляться без смены версии — парсер
должен их игнорировать. **Если `schema_version` ≠ 1 — остановите импорт и
сообщите**, не пишите данные вслепую.

### Связи

```
meal_categories (key) ◄── products.meal_categories[]      (массив ключей)
                      ◄── ration_slots.slot_type
                      ◄── iiko_category_map.slot_key

meal_times ◄── calorie_category_meals.meal_time_id ──► calorie_categories
           ◄── ration_slots.meal_time_id

calorie_categories.kcal ◄── rations.kcal     (по значению ккал, не по id!)

ration_groups ◄── rations.group_id ◄── ration_slots.ration_id ──► products
swap_groups   ◄── swap_items.swap_group_id ──► products
```

---

## 3. Таблицы

Поля с `| null` могут быть `null`. `null` означает «нет данных», а не ноль.

### `products` — блюда (главная таблица)

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | id блюда |
| `name` | string | название («Название в системе» iiko Server) |
| `article` | string \| null | артикул iiko — **лучший ключ для сопоставления с другими платформами** |
| `iiko_id` | string \| null | UUID позиции в iiko |
| `iiko_sku` | string \| null | артикул/код в iiko (служебный) |
| `iiko_category` | string \| null | категория во внешнем меню iiko, как есть |
| `meal_categories` | string[] | ключи категорий блюда, см. `meal_categories` |
| `packing` | string \| null | кратность / фасовка («порц», «шт») |
| `net_weight_g` | number \| null | масса нетто, г |
| `cost` | number \| null | себестоимость, ₸ |
| `sale_price` | number \| null | цена продажи, ₸ |
| `sale_price_manual` | bool | `true` — цена введена руками; `false` — рассчитана как себестоимость +67% |
| `markup` | number \| null | наценка, ₸ (`sale_price − cost`) |
| `markup_pct` | number \| null | наценка, % от себестоимости |
| `composition` | string \| null | состав, очищенный (так показывается на сайте и этикетках) |
| `composition_raw` | string \| null | состав как пришёл из техкарты iiko |
| `protein_100`, `fat_100`, `carbs_100` | number \| null | БЖУ на 100 г, г |
| `kcal_100`, `kj_100` | number \| null | энергия на 100 г |
| `protein_serving`, `fat_serving`, `carbs_serving` | number \| null | БЖУ на порцию, г |
| `kcal_serving`, `kj_serving` | number \| null | энергия на порцию |
| `photo_url` | string \| null | полный URL фото, открыт без авторизации |
| `iiko_synced_at` | datetime \| null | когда блюдо последний раз обновлялось из iiko |

Блюда **не удаляются**, когда пропадают из меню iiko: на них ссылаются рационы.
Себестоимость есть не у всех блюд (не производились) — это нормально.

### `meal_categories` — категории блюд (справочник, фиксированный)

| Поле | Тип | Описание |
|---|---|---|
| `key` | string | ключ: `breakfast`, `hot_400`, `hot_500`, `soup`, `salad`, `dessert`, `smoothie`, `sandwich`, `jkt`, `extra` |
| `name` | string | «Завтрак», «Горячее 400-500», … |
| `for_rations` | bool | участвует ли в сборке рационов (`extra` — «Доп. товары» — нет) |

### `meal_times` — приёмы пищи

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | |
| `name` | string | «Завтрак», «Обед», «Перекус» … |
| `icon` | string | эмодзи |
| `order` | int | порядок показа |

### `calorie_categories` — калоражи (нормы КБЖУ рациона)

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | |
| `name` | string | «1500 ккал» |
| `kcal` | int | калорийность, **уникальна** — по ней ссылаются рационы |
| `kcal_min`, `kcal_max` | int | допустимый диапазон ккал за день |
| `protein_min`, `protein_max` | int | белки за день, г |
| `fat_min`, `fat_max` | int | жиры за день, г |
| `carbs_min`, `carbs_max` | int | углеводы за день, г |
| `order` | int | порядок показа |
| `created_at`, `updated_at` | datetime | |

### `calorie_category_meals` — приёмы пищи в калораже

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | |
| `calorie_category_id` | int | → `calorie_categories.id` |
| `meal_time_id` | int | → `meal_times.id` |
| `order` | int | порядок приёма пищи в дне |

### `ration_groups` — группы рационов

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | |
| `name` | string | «ДИАБЕТ 1800» |
| `description` | string \| null | |
| `shared_editing` | bool | служебный флаг прав редактирования |
| `created_by` | string \| null | логин автора |
| `created_at` | datetime | |

### `rations` — рационы (один день питания)

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | |
| `group_id` | int \| null | → `ration_groups.id` |
| `name` | string | «Диабет 1800 день 3» |
| `kcal` | int | калораж → `calorie_categories.kcal` (**по значению**; калоража может уже не быть) |
| `wishes` | string \| null | пожелания к составу рациона |
| `notes` | string \| null | примечания |
| `order` | int | порядок в группе |
| `created_by` | string \| null | логин автора |
| `created_at`, `updated_at` | datetime | |

### `ration_slots` — блюда в рационе

| Поле | Тип | Описание |
|---|---|---|
| `id` | int | |
| `ration_id` | int | → `rations.id` |
| `meal_time_id` | int \| null | → `meal_times.id` |
| `slot_type` | string \| null | → `meal_categories.key` |
| `product_id` | int \| null | → `products.id`; `null` — слот пока пустой |
| `order` | int | порядок |

КБЖУ рациона в выгрузке не хранится — это сумма `*_serving` блюд его слотов.

### `swap_groups` / `swap_items` — блюда на замену

`swap_groups`: `id`, `name` («Супы на замену»), `order`, `created_at`.
`swap_items`: `id`, `swap_group_id` → `swap_groups.id`, `product_id` → `products.id`, `order`.

### `materials` — упаковка и расходники (не блюда)

`id`, `article` (string \| null), `name`, `unit` («1 шт»), `order`.

### `iiko_category_map` — соответствие категорий iiko → категории платформы

`id`, `iiko_name` (название категории во внешнем меню iiko), `slot_key` → `meal_categories.key`.

---

## 4. Как синхронизировать

Выгрузка — полный снимок, поэтому самый простой и надёжный алгоритм:

1. `GET /api/export/`. При не-200 — не трогать данные, завести алерт.
2. Проверить `schema_version == 1`.
3. В **одной транзакции** для каждой таблицы:
   - `upsert` всех строк по `id`;
   - удалить у себя строки этого источника, `id` которых нет в выгрузке
     (удалённые рационы, слоты, замены).
4. Порядок — справочники раньше ссылающихся:
   `meal_categories → meal_times → products → calorie_categories →
   calorie_category_meals → ration_groups → rations → ration_slots →
   swap_groups → swap_items → materials → iiko_category_map`.
   Удаление — в обратном порядке.
5. Сохранить `generated_at` как время последней успешной синхронизации.

Если в общей базе таблицы общие для нескольких платформ, храните
`source = 'olive-nutri-baza'` и `source_id = id` и делайте upsert по
`(source, source_id)`. Для связи блюд с другими системами используйте
`article` (артикул iiko) — он одинаковый во всех системах, работающих с iiko.

---

## 5. Пример таблиц в Supabase

Вариант «одна схема на источник». Названия колонок совпадают с JSON.

```sql
create schema if not exists olive;

create table olive.meal_categories (
  key          text primary key,
  name         text not null,
  for_rations  boolean not null
);

create table olive.meal_times (
  id     int primary key,
  name   text not null,
  icon   text,
  "order" int not null default 0
);

create table olive.products (
  id                 int primary key,
  name               text not null,
  article            text,
  iiko_id            text,
  iiko_sku           text,
  iiko_category      text,
  meal_categories    text[] not null default '{}',
  packing            text,
  net_weight_g       numeric,
  cost               numeric,
  sale_price         numeric,
  sale_price_manual  boolean not null default false,
  markup             numeric,
  markup_pct         numeric,
  composition        text,
  composition_raw    text,
  protein_100 numeric, fat_100 numeric, carbs_100 numeric, kcal_100 numeric, kj_100 numeric,
  protein_serving numeric, fat_serving numeric, carbs_serving numeric,
  kcal_serving numeric, kj_serving numeric,
  photo_url          text,
  iiko_synced_at     timestamptz,
  synced_at          timestamptz not null default now()
);
create index on olive.products (article);

create table olive.calorie_categories (
  id int primary key, name text not null, kcal int not null unique,
  kcal_min int, kcal_max int, protein_min int, protein_max int,
  fat_min int, fat_max int, carbs_min int, carbs_max int,
  "order" int, created_at timestamptz, updated_at timestamptz
);

create table olive.calorie_category_meals (
  id int primary key,
  calorie_category_id int not null references olive.calorie_categories(id) on delete cascade,
  meal_time_id        int not null references olive.meal_times(id) on delete cascade,
  "order" int
);

create table olive.ration_groups (
  id int primary key, name text not null, description text,
  shared_editing boolean, created_by text, created_at timestamptz
);

create table olive.rations (
  id int primary key,
  group_id int references olive.ration_groups(id) on delete cascade,
  name text not null, kcal int not null, wishes text, notes text,
  "order" int, created_by text, created_at timestamptz, updated_at timestamptz
);

create table olive.ration_slots (
  id int primary key,
  ration_id    int not null references olive.rations(id) on delete cascade,
  meal_time_id int references olive.meal_times(id) on delete set null,
  slot_type    text references olive.meal_categories(key),
  product_id   int references olive.products(id) on delete set null,
  "order" int
);

create table olive.swap_groups (
  id int primary key, name text not null, "order" int, created_at timestamptz
);

create table olive.swap_items (
  id int primary key,
  swap_group_id int not null references olive.swap_groups(id) on delete cascade,
  product_id    int not null references olive.products(id) on delete cascade,
  "order" int
);

create table olive.materials (
  id int primary key, article text, name text not null, unit text, "order" int
);

create table olive.iiko_category_map (
  id int primary key, iiko_name text not null unique,
  slot_key text references olive.meal_categories(key)
);
```

---

## 6. Пример ежедневного импорта (Python)

Прямое подключение к Postgres Supabase (строка подключения из
Project Settings → Database). Запускать cron'ом / GitHub Actions / Supabase
Edge Function по расписанию — на ваш выбор.

```python
import os
import requests
import psycopg2
from psycopg2.extras import execute_values

URL = "https://olive-nutri-baza.kz/api/export/"
TOKEN = os.environ["OLIVE_EXPORT_TOKEN"]
DSN = os.environ["SUPABASE_DB_URL"]

# таблица -> первичный ключ; порядок важен (справочники раньше ссылающихся)
TABLES = [
    ("meal_categories", "key"),
    ("meal_times", "id"),
    ("products", "id"),
    ("calorie_categories", "id"),
    ("calorie_category_meals", "id"),
    ("ration_groups", "id"),
    ("rations", "id"),
    ("ration_slots", "id"),
    ("swap_groups", "id"),
    ("swap_items", "id"),
    ("materials", "id"),
    ("iiko_category_map", "id"),
]

resp = requests.get(URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
resp.raise_for_status()
data = resp.json()
assert data["schema_version"] == 1, f"новая версия схемы: {data['schema_version']}"

with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
    # удаление — в обратном порядке, чтобы не упереться во внешние ключи
    for table, pk in reversed(TABLES):
        keys = [row[pk] for row in data[table]]
        cur.execute(
            f'delete from olive.{table} where not ({pk} = any(%s))', (keys,)
        )
    for table, pk in TABLES:
        rows = data[table]
        if not rows:
            continue
        cols = list(rows[0].keys())
        quoted = ", ".join(f'"{c}"' for c in cols)
        updates = ", ".join(f'"{c}" = excluded."{c}"' for c in cols if c != pk)
        execute_values(
            cur,
            f'insert into olive.{table} ({quoted}) values %s '
            f'on conflict ({pk}) do update set {updates}',
            [[row[c] for c in cols] for row in rows],
        )
    # conn закоммитится при выходе из with; при исключении — откат

print("OK", data["generated_at"], data["counts"])
```

Если у вас в таблицах `synced_at` и других колонок больше, чем в JSON, — это
нормально: вставляются только колонки из выгрузки.

---

## 7. Контакты и изменения

- Изменения формата фиксируются в этом документе и в `schema_version`.
- Если нужны дополнительные поля или отдельные выборки — просите, добавим.
- Код эндпоинта: `myapp/export_api.py` в репозитории nutri-baza.
