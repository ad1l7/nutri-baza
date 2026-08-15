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
