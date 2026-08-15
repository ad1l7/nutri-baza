"""Этикетка блюда для принтера Zebra ZT411.

Этикетка рисуется здесь, на сервере: одна и та же картинка идёт и в превью
на вкладке, и в ZPL-команду ^GFA на принтер. Поэтому «что вижу, то и печатаю»
выполняется буквально, а раскладка живёт в одном месте.

Размер — 100×130 мм при 203 dpi = 799×1039 точек (как в шаблоне Zebra Designer).
"""
import os
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFont

DPMM = 203 / 25.4
WIDTH, HEIGHT = 799, 1039        # 100 × 130 мм при 203 dpi
PAD = int(4 * DPMM)              # поля 4 мм
DEFAULT_SHELF_HOURS = 72

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


# ── помощники отрисовки ──────────────────────────────────────────────────────

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


def _para(draw, text, x, y, max_width, size, bold=False, line_height=1.28):
    font = _font(size, bold)
    for line in _wrap(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=0)
        y += int(size * line_height)
    return y


def _num(value, digits=1):
    if value is None:
        return "—"
    return ("%.*f" % (digits, float(value))).replace(".", ",")


def _triangle(draw, x, y, size, digit, caption):
    """Треугольник переработки с цифрой и подписью."""
    points = [(x + size / 2, y), (x + size, y + size * .86), (x, y + size * .86)]
    draw.line(points + [points[0]], fill=0, width=max(2, int(size * .05)))
    draw.text((x + size / 2, y + size * .34), digit,
              font=_font(int(size * .38), True), fill=0, anchor="mm")
    draw.text((x + size / 2, y + size * .99), caption,
              font=_font(int(size * .21)), fill=0, anchor="mm")


def _eac(draw, x, y, size):
    draw.rectangle([x, y, x + size * 1.3, y + size * .8], outline=0,
                   width=max(2, int(size * .06)))
    draw.text((x + size * .65, y + size * .4), "EAC",
              font=_font(int(size * .42), True), fill=0, anchor="mm")


def _fork_glass(draw, x, y, size):
    """Знак «пригодно для контакта с пищей» — вилка и бокал."""
    w = max(2, int(size * .05))
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
    """Рамка с датой — как в образце, с «иконкой» слева внутри."""
    draw.rectangle([x, y, x + width, y + height], outline=0, width=2)
    draw.rectangle([x + 5, y + 5, x + height - 5, y + height - 5], outline=0, width=2)
    draw.text((x + height + 6, y + height / 2), text,
              font=_font(int(height * .55), True), fill=0, anchor="lm")


# ── этикетка ─────────────────────────────────────────────────────────────────

def render_label(product, made_at, shelf_hours=DEFAULT_SHELF_HOURS):
    """Возвращает монохромное изображение этикетки для блюда."""
    image = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(image)

    best_before = made_at + timedelta(hours=shelf_hours)
    fmt = lambda moment: moment.strftime("%d.%m.%Y  %H:%M")

    composition = product.composition_clean or product.composition or ""
    weight_g = float(product.net_weight * 1000) if product.net_weight else None

    right_column = 165                      # место под значки справа
    width_text = WIDTH - 2 * PAD - right_column
    width_full = WIDTH - 2 * PAD
    y = PAD + 8

    # ── Верхний блок. Место казахского текста: пока тот же текст по-русски,
    #    чтобы было видно, сколько площади он займёт после перевода. ──
    if composition:
        y = _para(draw, "Құрамы / Состав: " + composition + ". " + FIXED["allergens"],
                  PAD, y, width_text, 15)
    y = _para(draw, FIXED["storage"].format(hours=shelf_hours), PAD, y, width_text, 15)
    y = _para(draw, FIXED["gas"], PAD, y, width_text, 15)
    y = _para(draw, FIXED["producer"], PAD, y, width_text, 15)
    y = _para(draw, FIXED["address"], PAD, y, width_text, 15)
    y = _para(draw, FIXED["phone"], PAD, y, width_text, 15)
    y += 12

    # ── Значки справа ──
    marks_x = WIDTH - PAD - right_column + 12
    _triangle(draw, marks_x, PAD + 4, 64, "7", "OTHER")
    _triangle(draw, marks_x + 90, PAD + 4, 64, "5", "PP")
    _fork_glass(draw, marks_x, PAD + 104, 62)
    _eac(draw, marks_x + 88, PAD + 112, 54)

    # ── Даты: подпись слева, рамка справа ──
    _para(draw, "Дайындалған күні мен уақыты / Дата и время изготовления:", PAD, y, 340, 15)
    _date_box(draw, PAD + 355, y - 4, 215, 30, fmt(made_at))
    y += 40
    _para(draw, "Жарамдылық мерзімі / Годен до:", PAD, y, 230, 15)
    _date_box(draw, PAD + 245, y - 4, 215, 30, fmt(best_before))
    y += 52

    # ── Название (верхнее — место казахского) ──
    name = _clean_name(product.name)
    for line in _wrap(draw, name, _font(40, True), width_full):
        draw.text((PAD, y), line, font=_font(40, True), fill=0)
        y += 48

    # ── Вертикальная строка СТ ТОО у правого края ──
    st_font = _font(15)
    strip = Image.new("1", (int(draw.textlength(FIXED["st"], font=st_font)) + 6, 22), 1)
    ImageDraw.Draw(strip).text((0, 0), FIXED["st"], font=st_font, fill=0)
    image.paste(strip.rotate(90, expand=True), (WIDTH - PAD - 20, int(HEIGHT * .34)))

    # ── Нижняя половина: центр этикетки намеренно пустой ──
    y = int(HEIGHT * .58)
    for line in _wrap(draw, name, _font(40, True), width_full):
        draw.text((PAD, y), line, font=_font(40, True), fill=0)
        y += 48
    y += 12

    if composition:
        y = _para(draw, "Состав: " + composition + ". " + FIXED["allergens"],
                  PAD, y, width_full, 15)
    y += 8
    y = _para(draw, FIXED["iso"], PAD, y, width_full, 14)
    y = _para(draw, "Пищевая ценность продукта:", PAD, y, width_full - 190, 14)
    y = _para(draw, "Белки — %sг; Жиры — %sг; Углеводы — %sг"
              % (_num(product.protein_per_serving), _num(product.fat_per_serving),
                 _num(product.carbs_per_serving)),
              PAD, y, width_full - 190, 14)
    y = _para(draw, "Энергетическая ценность %s Ккал / %s КДж"
              % (_num(product.kcal_per_serving, 0), _num(product.kj_per_serving, 0)),
              PAD, y, width_full, 14)

    draw.text((WIDTH - PAD - 175, HEIGHT - 96), "Таза салмағы/", font=_font(15), fill=0)
    draw.text((WIDTH - PAD - 175, HEIGHT - 76), "Масса нетто: %s г" % _num(weight_g, 0),
              font=_font(17, True), fill=0)
    return image


def _clean_name(name):
    """Убирает служебные части названия из iiko: «ПП* Упак», «(1порц)»."""
    result = (name or "").replace("ПП* Упак ", "").replace("ПП*Упак ", "")
    for tail in (" (1порц)", " (1шт)", "(1порц)", "(1шт)"):
        result = result.replace(tail, "")
    return result.strip()


# ── ZPL ──────────────────────────────────────────────────────────────────────

def image_to_zpl(image, copies=1, speed=4, darkness=15):
    """Картинка → ZPL-команда ^GFA (тот же способ, что и в старом файле печати)."""
    bytes_per_row = (WIDTH + 7) // 8
    total = bytes_per_row * HEIGHT
    pixels = image.load()

    chunks = []
    for y in range(HEIGHT):
        for block in range(bytes_per_row):
            byte = 0
            for bit in range(8):
                x = block * 8 + bit
                if x < WIDTH and pixels[x, y] == 0:   # 0 = чёрное
                    byte |= 0x80 >> bit
            chunks.append("%02X" % byte)

    return "\n".join([
        "~SD%d" % max(0, min(30, darkness)),
        "^XA",
        "^PR%d" % speed,
        "^PW%d" % WIDTH,
        "^LL%d" % HEIGHT,
        "^PQ%d" % max(1, copies),
        "^FO0,0",
        "^GFA,%d,%d,%d,%s" % (total, total, bytes_per_row, "".join(chunks)),
        "^FS",
        "^XZ",
    ])
