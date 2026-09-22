# Как выгружается себестоимость из iiko

Кратко: себестоимость блюд берётся из **OLAP-отчёта iiko Server** по расходным
накладным за последние 60 дней. Код: `myapp/iiko_sync.py`
(`IikoServerClient.get_cost_report`, `_parse_cost_report`, `_lookup_cost`).

## 1. Авторизация в iiko Server

```
GET {server_url}/api/auth?login=<логин>&pass=<пароль>
```
Ответ — токен (строка). Дальше он передаётся параметром `?key=<токен>`.
В конце **обязательно** `GET /api/auth/logout?key=<токен>`, даже при ошибке —
иначе iiko исчерпает сессии.

## 2. Какой отчёт запрашиваем

```
POST {server_url}/api/v2/reports/olap?key=<токен>
Accept: application/json
```

| Параметр | Значение |
|---|---|
| Тип отчёта | `TRANSACTIONS` |
| Группировка (строки) | `DateTime.DateTyped`, `Product.Id`, `Product.Num`, `Product.Name` |
| Показатели | `Sum.Incoming` (сумма), `Amount.Out` (количество) |
| Период (`DateTime.OperDayFilter`) | с `сегодня − 60 дней` по `сегодня + 2 дня`, `includeLow=true`, `includeHigh=false` |
| Группа товаров (`Product.ThirdParent`) | `ЗДОРОВОЕ ПИТАНИЕ` |
| Тип транзакции (`TransactionType`) | `OUTGOING_INVOICE` (расходная накладная) |
| Контрагент | не фильтруем — все |

Тело запроса:

```json
{
  "reportType": "TRANSACTIONS",
  "groupByRowFields": ["DateTime.DateTyped", "Product.Id", "Product.Num", "Product.Name"],
  "groupByColFields": [],
  "aggregateFields": ["Sum.Incoming", "Amount.Out"],
  "filters": {
    "DateTime.OperDayFilter": {
      "filterType": "DateRange",
      "from": "2026-07-24T00:00:00",
      "to":   "2026-09-24T00:00:00",
      "includeLow": true,
      "includeHigh": false,
      "periodType": "CUSTOM"
    },
    "Product.ThirdParent": { "filterType": "IncludeValues", "values": ["ЗДОРОВОЕ ПИТАНИЕ"] },
    "TransactionType":     { "filterType": "IncludeValues", "values": ["OUTGOING_INVOICE"] }
  }
}
```

## 3. Как считаем цену за единицу

Для каждой строки отчёта:

1. **Себестоимость = `Sum.Incoming` / `Amount.Out`.**
2. Строки, где количество **или сумма** ≤ 0, пропускаем — нулевая сумма значит
   списание с нулевого остатка, а не бесплатное блюдо.
3. Если по блюду несколько дней — берём **самый свежий** учётный день
   (не среднее).

Получаются два индекса: по GUID (`Product.Id`) и по артикулу (`Product.Num`).

## 4. Как сопоставляем с блюдами на сайте

1. По GUID блюда из iiko.
2. Если не нашлось — по артикулу (`iiko_sku`).
3. По названию **не ищем** (разные блюда бывают с одинаковым именем).

Найденное значение округляется до 2 знаков и пишется в `Product.cost`.
Не нашлось — поле не трогаем (на сайте показывается прочерк).

## 5. Что происходит после

`Product.save()` пересчитывает цену продажи: **себестоимость × 1,67**
(`MARKUP_TARGET_PCT = 67`), с округлением вверх до целого тенге.
Исключения: цена задана вручную (`sale_price_manual = True`) или себестоимости нет.

## 6. Частые проблемы

- **Всё стало нулём** — кто-то провёл накладную с нулевой ценой; проверить,
  что фильтр `total <= 0` на месте.
- **Отчёт пустой** — проверить период и группу `ЗДОРОВОЕ ПИТАНИЕ`.
- **`Grouping is not allowed`** — для группировки нужен `DateTime.DateTyped`,
  а `DateTime.OperDayFilter` — только для фильтра.
- **Не видно завтрашних накладных** — верхняя граница должна быть `+2 дня`.
- **У блюда нет себестоимости** — его ещё не производили/не отгружали, это норма.

Подробнее и с историей ошибок — `PROJECT_GUIDE.md`, раздел 8.
