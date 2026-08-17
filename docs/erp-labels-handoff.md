# Этикетки в ERP: интеграция с каталогом Olive

Документ для агента, который делает печать этикеток на стороне ERP.
Сторона Olive уже готова — здесь описано, что она отдаёт и что нужно построить у вас.

---

## 1. Расклад

Два независимых Django-проекта:

| | **Olive** (`olive-nutri-baza.kz`) | **ERP** (вы) |
|---|---|---|
| Что это | база блюд: состав, БЖУ, масса. Данные приезжают из iiko | ERP-система, печатает этикетки нескольким заказчикам |
| Роль в интеграции | источник данных, только чтение | владелец печати: макеты, реквизиты, журнал |
| Знает про другую сторону | ничего | знает, что Olive — один из источников |

**Главное решение:** движок этикеток живёт в ERP, а не в Olive. Иначе для Olive этикетку рисует один сервер, для остальных заказчиков — другой, и через полгода это два разных кода, делающих одно и то же.

**Второе решение:** ERP хранит у себя копию каталога и печатает из неё. В Olive ходит только синхронизация — не печать. Печать в цехе не должна вставать из-за сети, а при претензии по продукции нужно знать текст, который был на этикетке в день печати, а не текущий состав в iiko.

Физически печать идёт так: сервер ERP отдаёт браузеру оператора текст ZPL → браузер через **Zebra Browser Print** (`https://localhost:9101`) отправляет его на принтер **Zebra ZT411**, подключённый к тому же компьютеру. Сервер с принтером не соединяется никогда, поэтому расположение сервера роли не играет.

---

## 2. API Olive (готово, менять не нужно)

### Доступ

```
База:     https://olive-nutri-baza.kz
Заголовок: X-Label-Token: <токен>
Методы:    только GET (на POST придёт 405)
```

Токен передаётся отдельно, в этом документе его нет. Сессии/куки не принимаются — только заголовок. Без заголовка или с неверным токеном:

```json
HTTP 401
{"error": "unauthorized"}
```

### `GET /api/v1/labels/products/` — весь каталог

Отдаётся целиком, без пагинации (порядка 270 блюд). Блюда без состава в выдачу не попадают — из них этикетку не сделать.

```json
{
  "source": "olive",
  "count": 269,
  "results": [ { …объект блюда… } ]
}
```

### `GET /api/v1/labels/products/<id>/` — одно блюдо

Тот же объект. Если блюда нет или у него пустой состав:

```json
HTTP 404
{"error": "not_found"}
```

### Объект блюда

```json
{
  "id": 690,
  "article": "15415",
  "name": "ПП* Упак Жасыл салат алмұртпен (1порц)",
  "name_print": "Жасыл салат алмұртпен",
  "composition": "Груша, Сыр Адыгейский, Руккола, Помидоры черри, Огурцы, Орех кедровый",
  "allergens": ["Орехи", "Молоко"],
  "net_weight_g": 136.0,
  "nutrition_per_serving": {
    "protein": 5.88, "fat": 6.33, "carbs": 4.32, "kcal": 97.82, "kj": 409.28
  },
  "nutrition_per_100g": {
    "protein": 4.33, "fat": 4.66, "carbs": 3.18, "kcal": 71.93, "kj": 300.94
  },
  "synced_at": "2026-07-18T11:04:15.630118+00:00"
}
```

Что важно знать про поля:

| Поле | Смысл |
|---|---|
| `id` | ключ блюда **в Olive**. У себя храните как `external_id`, своим первичным ключом не делайте |
| `name` | как в каталоге Olive, со служебными хвостами iiko |
| `name_print` | **это печатать.** Уже очищено от `ПП* Упак`, `(1порц)`, `(1шт)` |
| `composition` | прочищенный через справочник ингредиентов состав. Печатать его |
| `allergens` | список названий. На текущем макете Olive не печатается (там общая фраза-дисклеймер), но для других заказчиков может пригодиться |
| `net_weight_g` | **уже граммы.** Ни на что не умножать |
| `nutrition_per_serving` | на порцию — то, что идёт на этикетку Olive |
| `nutrition_per_100g` | на 100 г — на случай другого формата этикетки |
| `synced_at` | когда блюдо последний раз обновлялось из iiko. UTC |

Любое числовое поле может быть `null` — это «не заполнено», и это не то же самое, что 0. На этикетке такие значения печатаются как `—`.

### Чего в API нет и не будет

- **Реквизитов производителя** (ТОО, адрес, телефон, номер СТ, ISO, фраза про газовую среду и аллергены). Они принадлежат тому, кто печатает, а не блюду: у второго заказчика будут свои. Заводите их у себя как отдельную сущность.
- **Срока хранения, размеров наклейки, скорости и плотности печати.** Это настройки печати, их владелец — ERP.
- **Фото блюда.** Не нужно: середина наклейки оставлена пустой намеренно, там уже напечатаны рисунок и QR-код типографским способом.

---

## 3. Что построить в ERP

### 3.1 Модели

```python
class Producer(models.Model):
    """Реквизиты на этикетке. У каждого заказчика свои."""
    code           = models.SlugField(unique=True)          # "olive"
    title          = models.CharField(max_length=200)       # 'ТОО "Фуд завод"'
    address        = models.CharField(max_length=300)
    phone          = models.CharField(max_length=100)
    cert_st        = models.CharField(max_length=200)       # "СТ ТОО 21034002189-01-2021"
    text_iso       = models.CharField(max_length=300)
    text_gas       = models.CharField(max_length=300)
    text_allergens = models.TextField()
    default_shelf_hours = models.PositiveIntegerField(default=72)


class CatalogSource(models.Model):
    """Откуда тянем блюда."""
    code      = models.SlugField(unique=True)               # "olive"
    base_url  = models.URLField()                           # https://olive-nutri-baza.kz
    token     = models.CharField(max_length=200)            # из переменной окружения, не в коде
    producer  = models.ForeignKey(Producer, on_delete=models.PROTECT)
    synced_at = models.DateTimeField(null=True, blank=True)


class ExternalProduct(models.Model):
    """Копия блюда. Печатаем только отсюда."""
    source      = models.ForeignKey(CatalogSource, on_delete=models.CASCADE)
    external_id = models.CharField(max_length=50)
    article     = models.CharField(max_length=100, blank=True)
    name        = models.CharField(max_length=300)
    name_print  = models.CharField(max_length=300)
    composition = models.TextField(blank=True)
    allergens   = models.JSONField(default=list)
    net_weight_g = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    # БЖУ на порцию и на 100 г — DecimalField(null=True) каждое
    raw         = models.JSONField()          # ответ API как есть, для разбора расхождений
    is_active   = models.BooleanField(default=True)
    synced_at   = models.DateTimeField()

    class Meta:
        unique_together = [("source", "external_id")]


class PrintedLabel(models.Model):
    """Журнал: что реально уехало на принтер."""
    product   = models.ForeignKey(ExternalProduct, on_delete=models.PROTECT)
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    copies    = models.PositiveIntegerField()
    made_at   = models.DateTimeField()        # дата изготовления с этикетки
    shelf_hours = models.PositiveIntegerField()
    snapshot  = models.JSONField()            # поля на момент печати
    created_at = models.DateTimeField(auto_now_add=True)
```

`PrintedLabel.snapshot` — не избыточность. Состав в iiko меняется, а этикетка уже уехала с продукцией; при разборе претензии нужен текст на момент печати.

### 3.2 Синхронизация

Management-команда `sync_catalog --source olive`:

1. `GET /api/v1/labels/products/` с заголовком `X-Label-Token`, таймаут 30 с, 2–3 ретрая.
2. Upsert по `(source, external_id)`, в `raw` кладём объект целиком.
3. Блюда, которых нет в ответе, — `is_active = False`. **Не удалять:** на них ссылается журнал печати.
4. Если запрос упал — ничего не трогаем, пишем ошибку в лог. Старая копия рабочая, это лучше, чем пустой каталог.
5. Обновляем `CatalogSource.synced_at`.

Запуск: cron раз в час + кнопка «Обновить каталог» в интерфейсе. В UI показывайте, когда синхронизация была последний раз, — оператор должен видеть, что данные свежие.

### 3.3 Движок этикетки

Исходник рабочего макета Olive — в приложении A. Это Pillow: рисуется PNG, затем тот же растр переводится в ZPL-команду `^GFA`. Такой способ выбран сознательно — превью на экране и то, что уходит на принтер, это буквально одна картинка, «что вижу, то и печатаю».

При переносе в ERP:

1. **Общее — в отдельный модуль:** `Block`, `_wrap`, `_font`, `image_to_zpl`. Ими будут пользоваться макеты всех заказчиков.
2. **Раскладка Olive — отдельный макет.** Она специфична: пустая середина под рисунок и QR (`ART_TOP`/`ART_BOTTOM`), вертикальная строка СТ вдоль правого края, две зоны с автоподбором кегля. У следующего заказчика наклейка будет другая — не пытайтесь сделать один универсальный рендер.
3. **Словарь `FIXED` заменить на поля `Producer`.** Сейчас реквизиты прибиты в коде.
4. **Убрать умножение массы:** в исходнике `weight_g = float(product.net_weight * 1000)`, потому что в Olive масса лежит в килограммах. API отдаёт `net_weight_g` уже в граммах — умножение убрать, иначе получите 136 000 г.
5. **Убрать вызов `_clean_name`:** API отдаёт готовое `name_print`.
6. Сигнатура станет примерно такой:
   ```python
   render_label(product, producer, made_at, shelf_hours, width_mm, height_mm, margin_mm)
   ```

**Шрифты.** На сервере нужен DejaVu — в нём есть кириллица и казахские буквы (`ә`, `ұ`, `қ`, `ң`, `ө`, `і`, `ғ`, `һ`):

```bash
apt install fonts-dejavu-core
```

Путь `/usr/share/fonts/truetype/dejavu` уже в коде. Без этого пакета Pillow свалится на `load_default()` и вместо казахских букв напечатает мусор — проверять обязательно на живом принтере, на превью в браузере это иногда не бросается в глаза.

### 3.4 Значения по умолчанию

Взяты с рабочей вкладки Olive, менять без нужды не стоит:

| Параметр | Значение | Примечание |
|---|---|---|
| Ширина | 96 мм | наклейка 100 мм, но крайние миллиметры уходят за край печати |
| Высота | 130 мм | |
| Поля | 6 мм | |
| Разрешение | 203 dpi | ZT411 |
| Срок хранения | 72 ч | оператор меняет на форме |
| Время изготовления | сегодня, 17:00 | конец смены; оператор меняет |
| Скорость | 4 ips | |
| Плотность | 20 | диапазон 0–30 |

Ширину оператор подбирает под конкретную партию наклеек: если текст уходит за край — уменьшает на 2–3 мм. Оставьте это поле в интерфейсе, оно рабочее.

### 3.5 Интерфейс и печать

Три endpoint'а по образцу Olive:

- страница выбора блюд (список, чекбоксы, количество копий, параметры печати);
- `…/preview.png?<параметры>` — PNG одной этикетки;
- `…/zpl/?items=<id>:<копий>,<id>:<копий>&<параметры>` — текст ZPL для всей пачки.

Рабочий JS печати — в приложении B, копируется почти как есть. Логика: находим принтер через `GET https://localhost:9101/available`, забираем ZPL со своего сервера, отправляем `POST https://localhost:9101/write`.

Что нужно знать про Browser Print:
- это отдельная программа Zebra, установленная на компьютере оператора; без неё печать не работает вообще;
- `https://localhost:9101` — самоподписанный сертификат. При первом запуске надо один раз открыть этот адрес в том же браузере и принять исключение, иначе `fetch` будет молча падать;
- предпочитать USB-принтер: `printers.find(p => p.connection === 'usb') || printers[0]`;
- количество копий уходит в ZPL командой `^PQ`, а не повторной отправкой картинки.

Печать пишем в `PrintedLabel` **на сервере, при генерации ZPL** — не по факту успеха на принтере. Браузер о результате печати ничего достоверного не знает.

---

## 4. Грабли

1. **Не ходить в Olive при печати.** Только синхронизация. Иначе цех встанет вместе с сетью.
2. **Не подключаться к Postgres Olive напрямую.** Любая миграция там сломает ERP молча.
3. **`net_weight_g` уже в граммах** (см. 3.3 пункт 4). Самая вероятная ошибка при переносе.
4. **Числа бывают `null`** — печатать `—`, не `0` и не падать.
5. **Токен — в переменной окружения**, не в коде и не в репозитории.
6. **Ходить по HTTPS и по домену** `olive-nutri-baza.kz`: у Olive настроен `ALLOWED_HOSTS`, обращение по IP с чужим Host вернёт 400.
7. **Ответ отдаётся целиком** — не пытайтесь листать страницы, параметров пагинации нет.

## 5. Проверка, что связь есть

```bash
curl -H "X-Label-Token: <токен>" https://olive-nutri-baza.kz/api/v1/labels/products/ | head -c 400
```

Ожидается `{"source": "olive", "count": …`. Если пришёл `{"error": "unauthorized"}` — токен не тот или не задан на стороне Olive.

---

## Приложение A. Рабочий макет этикетки Olive (`labels.py`)

Переносить с правками из раздела 3.3.

```python
"""Этикетка блюда для принтера Zebra ZT411.

Этикетка рисуется здесь, на сервере: одна и та же картинка идёт и в превью
на вкладке, и в ZPL-команду ^GFA на принтер. Поэтому «что вижу, то и печатаю»
выполняется буквально, а раскладка живёт в одном месте.

Размер по умолчанию — 100×130 мм при 203 dpi. Ширину, высоту и поля можно
менять на вкладке: у наклеек бывает разная реальная печатная область, и если
текст уползает за край — уменьшают ширину, не трогая код.

Середина этикетки остаётся пустой: там на самой наклейке уже напечатаны
рисунок и QR-код.
"""
import os
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFont

DPI = 203
DPMM = DPI / 25.4
# Печатная ширина с запасом: на 100 мм крайние миллиметры уходили за край
# наклейки. Поднимается на вкладке, если на конкретных наклейках влезает больше.
DEFAULT_WIDTH_MM = 96
DEFAULT_HEIGHT_MM = 130
DEFAULT_MARGIN_MM = 6
DEFAULT_SHELF_HOURS = 72

# Свободная середина под рисунок и QR — доли от высоты этикетки
ART_TOP = 0.40
ART_BOTTOM = 0.63

# Шрифты: на сервере — DejaVu (есть кириллица и казахские буквы), локально — Arial
_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", r"C:\Windows\Fonts"]
_REGULAR = ["DejaVuSans.ttf", "arial.ttf"]
_BOLD = ["DejaVuSans-Bold.ttf", "arialbd.ttf"]
_font_cache = {}


def _font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        for directory in _FONT_DIRS:
            for name in (_BOLD if bold else _REGULAR):
                path = os.path.join(directory, name)
                if os.path.exists(path):
                    _font_cache[key] = ImageFont.truetype(path, size)
                    return _font_cache[key]
        _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# Постоянные надписи. Позже переедут на отдельную страницу «Реквизиты»,
# пока правятся здесь — меняются они раз в год.
FIXED = {
    "producer": 'Производитель: ТОО "Фуд завод"',
    "address": "Адрес: г.Алматы, ул. Жансугурова, 176А",
    "phone": "Тел: +7 777 133 14 29",
    "gas": "Продукт упакован в газомодифицированной среде",
    "allergens": ("Продукт может содержать следы не заявленных в составе "
                  "компонентов, которые являются аллергенами."),
    "iso": "Система менеджмента сертифицирована по СТ РК ISO 22000-2019",
    "st": "СТ ТОО 21034002189-01-2021",
    "storage": "Срок хранения: {hours} часа, при температуре от +2 до +6С.",
}


# ── текст ────────────────────────────────────────────────────────────────────

def _wrap(draw, text, font, max_width):
    lines, current = [], ""
    for word in str(text).split():
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class Block:
    """Накопитель строк: сначала считаем, сколько места займёт текст при данном
    размере шрифта, и только потом рисуем. Так подбирается кегль под зону."""

    def __init__(self, draw, x, width):
        self.draw, self.x, self.width = draw, x, width
        self.items = []
        self.height = 0

    def text(self, value, size, bold=False, width=None, gap=0, line_height=1.30):
        font = _font(size, bold)
        for line in _wrap(self.draw, value, font, width or self.width):
            self.items.append((line, font, self.height))
            self.height += int(size * line_height)
        self.height += gap

    def space(self, pixels):
        self.height += pixels

    def draw_at(self, y):
        for line, font, offset in self.items:
            self.draw.text((self.x, y + offset), line, font=font, fill=0)
        return y + self.height


def _num(value, digits=1):
    if value is None:
        return "—"
    return ("%.*f" % (digits, float(value))).replace(".", ",")


# ── значки ───────────────────────────────────────────────────────────────────

def _triangle(draw, x, y, size, digit, caption):
    points = [(x + size / 2, y), (x + size, y + size * .86), (x, y + size * .86)]
    draw.line(points + [points[0]], fill=0, width=max(2, int(size * .06)))
    draw.text((x + size / 2, y + size * .34), digit,
              font=_font(int(size * .40), True), fill=0, anchor="mm")
    draw.text((x + size / 2, y + size * 1.02), caption,
              font=_font(int(size * .24), True), fill=0, anchor="mm")


def _eac(draw, x, y, size):
    draw.rectangle([x, y, x + size * 1.3, y + size * .8], outline=0,
                   width=max(2, int(size * .07)))
    draw.text((x + size * .65, y + size * .4), "EAC",
              font=_font(int(size * .44), True), fill=0, anchor="mm")


def _fork_glass(draw, x, y, size):
    """Знак «пригодно для контакта с пищей» — вилка и бокал."""
    w = max(2, int(size * .06))
    draw.rectangle([x, y, x + size * .82, y + size * .82], outline=0, width=w)
    draw.line([(x + size * .22, y + size * .18), (x + size * .22, y + size * .64)], fill=0, width=w)
    draw.line([(x + size * .13, y + size * .18), (x + size * .13, y + size * .36)], fill=0, width=w)
    draw.line([(x + size * .31, y + size * .18), (x + size * .31, y + size * .36)], fill=0, width=w)
    draw.line([(x + size * .13, y + size * .36), (x + size * .31, y + size * .36)], fill=0, width=w)
    draw.line([(x + size * .50, y + size * .18), (x + size * .70, y + size * .18)], fill=0, width=w)
    draw.line([(x + size * .50, y + size * .18), (x + size * .60, y + size * .46)], fill=0, width=w)
    draw.line([(x + size * .70, y + size * .18), (x + size * .60, y + size * .46)], fill=0, width=w)
    draw.line([(x + size * .60, y + size * .46), (x + size * .60, y + size * .64)], fill=0, width=w)
    draw.line([(x + size * .49, y + size * .64), (x + size * .71, y + size * .64)], fill=0, width=w)


def _date_box(draw, x, y, width, height, text):
    draw.rectangle([x, y, x + width, y + height], outline=0, width=2)
    draw.rectangle([x + 5, y + 5, x + height - 5, y + height - 5], outline=0, width=2)
    draw.text((x + height + 8, y + height / 2), text,
              font=_font(int(height * .58), True), fill=0, anchor="lm")


# ── этикетка ─────────────────────────────────────────────────────────────────

def label_size(width_mm=DEFAULT_WIDTH_MM, height_mm=DEFAULT_HEIGHT_MM):
    return int(round(width_mm * DPMM)), int(round(height_mm * DPMM))


def render_label(product, made_at, shelf_hours=DEFAULT_SHELF_HOURS,
                 width_mm=DEFAULT_WIDTH_MM, height_mm=DEFAULT_HEIGHT_MM,
                 margin_mm=DEFAULT_MARGIN_MM):
    """Монохромная картинка этикетки.

    Рисуем в градациях серого (шрифты сглаживаются), а в конце переводим в 1 бит.
    Прямой рендер в монохром даёт рваные буквы — на 203 dpi это заметно."""
    width, height = label_size(width_mm, height_mm)
    margin = int(round(margin_mm * DPMM))

    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)

    best_before = made_at + timedelta(hours=shelf_hours)
    fmt = lambda moment: moment.strftime("%d.%m.%Y  %H:%M")
    composition = product.composition_clean or product.composition or ""
    weight_g = float(product.net_weight * 1000) if product.net_weight else None
    name = _clean_name(product.name)

    marks_w = int(round(21 * DPMM))          # колонка значков справа
    text_w = width - 2 * margin - marks_w
    full_w = width - 2 * margin
    art_top = int(height * ART_TOP)
    art_bottom = int(height * ART_BOTTOM)

    # ── Верхняя зона: реквизиты, даты, название. Кегль подбираем так,
    #    чтобы всё легло выше свободной середины. ──
    date_h = int(round(4.4 * DPMM))
    for size in range(18, 11, -1):
        top = Block(draw, margin, text_w)
        if composition:
            top.text("Құрамы / Состав: " + composition + ". " + FIXED["allergens"], size)
        top.text(FIXED["storage"].format(hours=shelf_hours), size)
        top.text(FIXED["gas"], size)
        top.text(FIXED["producer"], size)
        top.text(FIXED["address"], size)
        top.text(FIXED["phone"], size, gap=int(size * .7))
        dates_at = top.height
        top.space(2 * (date_h + 8))
        name_at = top.height
        top.text(name, size + 16, bold=True, width=full_w, line_height=1.20)
        if margin + top.height <= art_top - 6:
            break

    y = top.draw_at(margin)
    # Даты — подпись слева, рамка справа, поверх зарезервированного места
    dy = margin + dates_at
    box_w = int(round(27 * DPMM))
    draw.text((margin, dy + date_h * .28), "Дата и время изготовления:",
              font=_font(size, False), fill=0)
    _date_box(draw, width - margin - box_w, dy, box_w, date_h, fmt(made_at))
    dy += date_h + 8
    draw.text((margin, dy + date_h * .28), "Годен до:", font=_font(size, False), fill=0)
    _date_box(draw, width - margin - box_w, dy, box_w, date_h, fmt(best_before))

    # ── Значки справа сверху ──
    marks_x = width - margin - marks_w
    mark = int(round(8 * DPMM))
    _triangle(draw, marks_x, margin, mark, "7", "OTHER")
    _triangle(draw, marks_x + mark + 12, margin, mark, "5", "PP")
    _fork_glass(draw, marks_x, margin + mark + 26, mark)
    _eac(draw, marks_x + mark + 12, margin + mark + 30, int(mark * .85))

    # ── Вертикальная строка СТ ТОО у правого края, вдоль свободной середины ──
    st_font = _font(15)
    strip = Image.new("L", (int(draw.textlength(FIXED["st"], font=st_font)) + 6, 22), 255)
    ImageDraw.Draw(strip).text((0, 0), FIXED["st"], font=st_font, fill=0)
    image.paste(strip.rotate(90, expand=True), (width - margin - 22, art_top + 10))

    # ── Нижняя зона: название, состав, БЖУ, масса ──
    weight_h = int(round(11 * DPMM))          # место под массу нетто справа внизу
    for size in range(18, 11, -1):
        bottom = Block(draw, margin, full_w)
        bottom.text(name, size + 16, bold=True, line_height=1.20, gap=int(size * .5))
        if composition:
            bottom.text("Состав: " + composition + ". " + FIXED["allergens"], size,
                        gap=int(size * .4))
        bottom.text(FIXED["iso"], size - 1)
        bottom.text("Пищевая ценность продукта:", size - 1)
        bottom.text("Белки — %sг; Жиры — %sг; Углеводы — %sг"
                    % (_num(product.protein_per_serving), _num(product.fat_per_serving),
                       _num(product.carbs_per_serving)), size - 1)
        bottom.text("Энергетическая ценность %s Ккал / %s КДж"
                    % (_num(product.kcal_per_serving, 0), _num(product.kj_per_serving, 0)),
                    size - 1)
        if art_bottom + bottom.height <= height - margin - weight_h:
            break
    bottom.draw_at(art_bottom)

    draw.text((width - margin, height - margin - 42), "Таза салмағы/",
              font=_font(16), fill=0, anchor="ra")
    draw.text((width - margin, height - margin - 20), "Масса нетто: %s г" % _num(weight_g, 0),
              font=_font(19, True), fill=0, anchor="ra")

    # Сглаженный серый → чистый чёрно-белый растр для термопечати
    return image.point(lambda v: 0 if v < 150 else 255).convert("1")


def _clean_name(name):
    """Убирает служебные части названия из iiko: «ПП* Упак», «(1порц)»."""
    result = (name or "").replace("ПП* Упак ", "").replace("ПП*Упак ", "")
    for tail in (" (1порц)", " (1шт)", "(1порц)", "(1шт)"):
        result = result.replace(tail, "")
    return result.strip()


# ── ZPL ──────────────────────────────────────────────────────────────────────

def image_to_zpl(image, copies=1, speed=4, darkness=20):
    """Картинка → ZPL-команда ^GFA (тот же способ, что и в старом файле печати)."""
    width, height = image.size
    bytes_per_row = (width + 7) // 8
    total = bytes_per_row * height
    pixels = image.load()

    chunks = []
    for y in range(height):
        for block in range(bytes_per_row):
            byte = 0
            for bit in range(8):
                x = block * 8 + bit
                if x < width and pixels[x, y] == 0:   # 0 = чёрное
                    byte |= 0x80 >> bit
            chunks.append("%02X" % byte)

    return "\n".join([
        "~SD%d" % max(0, min(30, darkness)),
        "^XA",
        "^PR%d" % speed,
        "^PW%d" % width,
        "^LL%d" % height,
        "^PQ%d" % max(1, copies),
        "^FO0,0",
        "^GFA,%d,%d,%d,%s" % (total, total, bytes_per_row, "".join(chunks)),
        "^FS",
        "^XZ",
    ])
```

## Приложение B. Печать через Zebra Browser Print (фрагмент рабочей страницы)

```javascript
const $ = id => document.getElementById(id);
let active = null, device = null;

function log(msg, cls){ const d=document.createElement('div'); if(cls)d.className=cls; d.textContent=msg; $('log').prepend(d); }
function params(){
  return 'made_date='+encodeURIComponent($('made_date').value)
       + '&made_time='+encodeURIComponent($('made_time').value)
       + '&shelf='+encodeURIComponent($('shelf').value)
       + '&width='+encodeURIComponent($('width').value)
       + '&height='+encodeURIComponent($('height').value)
       + '&margin='+encodeURIComponent($('margin').value);
}

// Превью строит сервер — той же функцией, что готовит ZPL
function pick(id){
  active = id;
  document.querySelectorAll('.pitem').forEach(el => el.classList.toggle('active', +el.dataset.id === id));
  $('prev').src = '/labels/' + id + '/preview.png?' + params() + '&_=' + Date.now();
}
function refreshPreview(){ if(active) pick(active); }

function checked(){ return [...document.querySelectorAll('.pcb:checked')]; }
function sync(){
  const n = checked().length;
  $('cnt').textContent = 'выбрано: ' + n;
  $('print').textContent = 'ПЕЧАТЬ (' + n + ')';
  $('print').disabled = !(device && n);
  const all = document.querySelectorAll('.pcb').length;
  $('selall').checked = n > 0 && n === all;
  $('selall').indeterminate = n > 0 && n < all;
}
$('selall').onchange = e => {
  document.querySelectorAll('.pcb').forEach(cb => cb.checked = e.target.checked);
  sync();
};
['made_date','made_time','shelf','width','height','margin'].forEach(id => $(id).addEventListener('input', refreshPreview));

// ── Zebra Browser Print ──
const BP = 'https://localhost:9101';
$('find').onclick = async () => {
  $('led').className = 'led busy'; $('stat').textContent = 'Поиск…';
  try{
    const r = await fetch(BP + '/available');
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const list = await r.json();
    const printers = list.printer || [];
    if(!printers.length) throw new Error('список принтеров пуст');
    device = printers.find(p => p.connection === 'usb') || printers[0];
    $('led').className = 'led ok';
    $('stat').textContent = 'Принтер: ' + (device.name || device.uid);
    log('Принтер найден', 'okk');
  }catch(e){
    device = null; $('led').className = 'led err';
    $('stat').textContent = 'Не найден: ' + e.message;
    log('Browser Print недоступен: ' + e.message, 'er');
  }
  sync();
};

$('print').onclick = async () => {
  const items = checked().map(cb => {
    const row = cb.closest('.pitem');
    return cb.value + ':' + (row.querySelector('.copies').value || 1);
  }).join(',');
  const total = checked().reduce((s, cb) =>
    s + (+cb.closest('.pitem').querySelector('.copies').value || 1), 0);

  $('print').disabled = true;
  log('Готовлю ' + total + ' этикеток…');
  try{
    const url = '/labels/zpl/?items=' + encodeURIComponent(items) + '&' + params()
              + '&speed=' + $('speed').value + '&darkness=' + $('darkness').value;
    const zpl = await (await fetch(url)).text();
    const r = await fetch(BP + '/write', {
      method: 'POST',
      headers: {'Content-Type': 'text/plain;charset=UTF-8'},
      body: JSON.stringify({device: device, data: zpl}),
    });
    if(!r.ok) throw new Error('HTTP ' + r.status);
    log('Отправлено на принтер: ' + total + ' шт.', 'okk');
  }catch(e){
    log('Ошибка печати: ' + e.message, 'er');
  }
  $('print').disabled = false;
};

const first = document.querySelector('.pitem');
if(first) pick(+first.dataset.id);
sync();
```
