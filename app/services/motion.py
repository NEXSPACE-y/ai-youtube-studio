"""図解モーションエンジン v2。

PILでフレームを直接描画し、ffmpegへ流し込む。テンプレートは人間が作り込み、
AIはテキストパラメータだけを渡す(文字化け・崩れが構造的に起きない)。

v2の設計方針(「代わり映えしない」対策):
- 要素の登場タイミングはシーン尺に比例配分(画面がシーン全体を通して育つ)
- セクションごとのカラーテーマ(章の進行が色で分かる)
- シーン番号を種にしたレイアウトバリエーション
- 背景はゆっくりドリフト(完全静止画面を作らない)
"""

from __future__ import annotations

from typing import Iterator, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
FPS = 30

BG_TOP = (18, 22, 32)
BG_BOTTOM = (30, 36, 52)
CARD = (28, 33, 46, 235)
CARD_LINE = (70, 80, 105, 255)
TEXT = (235, 238, 245, 255)
SUB = (150, 158, 175, 255)
ACCENTS = [(76, 141, 255, 255), (47, 191, 113, 255), (242, 163, 60, 255),
           (139, 108, 242, 255), (228, 87, 79, 255), (52, 189, 189, 255)]

# セクション → テーマ色(章が進むと色が変わる)
_SECTION_ACCENT = {
    "hook": 0, "thesis": 5, "background": 1, "progression": 0,
    "turning_point": 2, "result": 1, "lesson": 3, "closing": 5,
}

_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# ---------- イージング ----------

def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.20158, 2.20158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _progress(t: float, start: float, dur: float) -> float:
    if dur <= 0:
        return 1.0
    return max(0.0, min(1.0, (t - start) / dur))


# ---------- 背景 ----------

_DRIFT = 60  # 背景ドリフト量(px)


def build_background(image_bytes: Optional[bytes]) -> Image.Image:
    """AI生成画像を暗くぼかした下地(ドリフト用に一回り大きく作る)。"""
    bw, bh = W + _DRIFT, H + _DRIFT * 9 // 16
    if image_bytes:
        try:
            import io

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            ratio = max(bw / img.width, bh / img.height)
            img = img.resize((int(img.width * ratio) + 1, int(img.height * ratio) + 1))
            left = (img.width - bw) // 2
            top = (img.height - bh) // 2
            img = img.crop((left, top, left + bw, top + bh))
            img = img.filter(ImageFilter.GaussianBlur(6))
            overlay = Image.new("RGB", (bw, bh), (10, 12, 18))
            return Image.blend(img, overlay, 0.55)
        except Exception:
            pass
    bg = Image.new("RGB", (bw, bh))
    px = bg.load()
    for y in range(bh):
        f = y / bh
        row = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * f) for i in range(3))
        for x in range(bw):
            px[x, y] = row
    return bg


# ---------- 部品 ----------

def _rounded_card(size: tuple[int, int], radius: int = 18,
                  fill=CARD, outline=CARD_LINE, accent=None) -> Image.Image:
    card = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius,
                        fill=fill, outline=outline, width=2)
    if accent:
        d.rounded_rectangle([0, 0, 8, size[1] - 1], radius=4, fill=accent)
    return card


def _text_size(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = font.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


def _paste_scaled(base: Image.Image, element: Image.Image, center: tuple[int, int],
                  scale: float, alpha: float) -> None:
    if scale <= 0.01 or alpha <= 0.01:
        return
    w = max(2, int(element.width * scale))
    h = max(2, int(element.height * scale))
    el = element.resize((w, h))
    if alpha < 1.0:
        a = el.getchannel("A").point(lambda v: int(v * alpha))
        el.putalpha(a)
    base.alpha_composite(el, (center[0] - w // 2, center[1] - h // 2))


def _accent_of(section: str, offset: int = 0):
    base = _SECTION_ACCENT.get(section, 0)
    return ACCENTS[(base + offset) % len(ACCENTS)]


# ---------- テンプレート(elementsを返す。startは後で尺に合わせて再配分) ----------

def _el_title_card(display: dict, section: str, seed: int) -> list[dict]:
    title = display.get("title", "")
    sub = (display.get("items") or [""])[0]
    accent = _accent_of(section)
    f_big, f_sub = _font(64), _font(30)
    tw, _ = _text_size(title, f_big)
    card = Image.new("RGBA", (max(tw + 120, 480), 176 if sub else 130), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.text(((card.width - tw) // 2, 14), title, font=f_big, fill=TEXT)
    d.rounded_rectangle([card.width // 2 - 70, 104, card.width // 2 + 70, 110],
                        radius=3, fill=accent)
    if sub:
        sw, _ = _text_size(sub, f_sub)
        d.text(((card.width - sw) // 2, 124), sub, font=f_sub, fill=SUB)
    return [{"img": card, "center": (W // 2, H // 2 - 40),
             "ease": ease_out_cubic, "rise": 40}]


def _el_keyword_pop(display: dict, section: str, seed: int) -> list[dict]:
    word = display.get("title", "")
    chips = (display.get("items") or [])[:3]
    accent = _accent_of(section)
    f = _font(58)
    tw, _ = _text_size(word, f)
    card = _rounded_card((tw + 110, 120), accent=accent)
    ImageDraw.Draw(card).text((58, 26), word, font=f, fill=TEXT)
    # 位置バリエーション(毎回ど真ん中に出ない)
    positions = [(W // 2, H // 2 - 40), (int(W * 0.38), int(H * 0.42)),
                 (int(W * 0.60), int(H * 0.40))]
    cx, cy = positions[seed % len(positions)]
    els = [{"img": card, "center": (cx, cy), "ease": ease_out_back, "pop": True}]
    f_chip = _font(28)
    chip_y = cy + 110
    for i, chip in enumerate(chips):
        cw, _ = _text_size(chip, f_chip)
        pill = _rounded_card((cw + 60, 56), radius=28,
                             accent=None, outline=_accent_of(section, i + 1))
        ImageDraw.Draw(pill).text((30, 12), chip, font=f_chip, fill=SUB)
        offset = (i - (len(chips) - 1) / 2) * (cw + 90)
        els.append({"img": pill, "center": (int(cx + offset), chip_y),
                    "ease": ease_out_cubic, "rise": 24})
    return els


def _el_bullets(display: dict, section: str, seed: int) -> list[dict]:
    els: list[dict] = []
    title = display.get("title", "")
    items = display.get("items") or []
    f_t, f_i = _font(42), _font(34)
    # レイアウトバリエーション: 中央 / 左寄せ(右に背景が見える)
    left_layout = seed % 2 == 1
    col_x = int(W * 0.32) if left_layout else W // 2
    if title:
        tw, _ = _text_size(title, f_t)
        head = Image.new("RGBA", (tw + 40, 66), (0, 0, 0, 0))
        d = ImageDraw.Draw(head)
        d.rounded_rectangle([0, 10, 10, 56], radius=4, fill=_accent_of(section))
        d.text((28, 6), title, font=f_t, fill=TEXT)
        els.append({"img": head, "center": (col_x, 140),
                    "ease": ease_out_cubic, "rise": 26})
    y = 240
    for i, item in enumerate(items):
        iw, _ = _text_size(item, f_i)
        card = _rounded_card((max(iw + 96, 420), 78),
                             accent=_accent_of(section, i))
        d = ImageDraw.Draw(card)
        d.ellipse([30, 31, 46, 47], fill=_accent_of(section, i))
        d.text((64, 18), item, font=f_i, fill=TEXT)
        els.append({"img": card, "center": (col_x, y),
                    "ease": ease_out_cubic,
                    "slide": -60 if left_layout else 60})
        y += 96
    return els


def _el_compare_cards(display: dict, section: str, seed: int) -> list[dict]:
    els: list[dict] = []
    title = display.get("title", "")
    items = (display.get("items") or [])[:3]
    f_t, f_c = _font(42), _font(36)
    if title:
        tw, _ = _text_size(title, f_t)
        head = Image.new("RGBA", (tw + 20, 60), (0, 0, 0, 0))
        ImageDraw.Draw(head).text((10, 4), title, font=f_t, fill=TEXT)
        els.append({"img": head, "center": (W // 2, 130),
                    "ease": ease_out_cubic, "rise": 26})
    n = max(1, len(items))
    card_w = min(340, (W - 160) // n)
    total = n * card_w + (n - 1) * 40
    x = (W - total) // 2 + card_w // 2
    for i, label in enumerate(items):
        accent = _accent_of(section, i)
        card = _rounded_card((card_w, 300), radius=22)
        d = ImageDraw.Draw(card)
        d.rounded_rectangle([0, 0, card_w - 1, 64], radius=22, fill=accent)
        d.rectangle([0, 40, card_w - 1, 64], fill=accent)
        lw, _ = _text_size(label, f_c)
        d.text(((card_w - lw) // 2, 10), label, font=f_c, fill=(255, 255, 255, 255))
        for row in range(3):
            d.rounded_rectangle([36, 110 + row * 52, card_w - 36, 126 + row * 52],
                                radius=8, fill=(60, 68, 90, 255))
        els.append({"img": card, "center": (x + i * (card_w + 40), H // 2 + 60),
                    "ease": ease_out_cubic, "rise": 70})
    return els


def _el_steps(display: dict, section: str, seed: int) -> list[dict]:
    """番号付きステップフロー(1→2→3)。手順・流れの説明に。"""
    els: list[dict] = []
    title = display.get("title", "")
    items = (display.get("items") or [])[:4]
    f_t, f_n, f_i = _font(42), _font(44), _font(28)
    if title:
        tw, _ = _text_size(title, f_t)
        head = Image.new("RGBA", (tw + 40, 66), (0, 0, 0, 0))
        d = ImageDraw.Draw(head)
        d.rounded_rectangle([0, 10, 10, 56], radius=4, fill=_accent_of(section))
        d.text((28, 6), title, font=f_t, fill=TEXT)
        els.append({"img": head, "center": (W // 2, 150),
                    "ease": ease_out_cubic, "rise": 26})
    n = max(1, len(items))
    card_w = min(270, (W - 200) // n)
    gap = 56
    total = n * card_w + (n - 1) * gap
    x0 = (W - total) // 2 + card_w // 2
    for i, item in enumerate(items):
        accent = _accent_of(section, i)
        card = _rounded_card((card_w, 190), radius=20)
        d = ImageDraw.Draw(card)
        d.ellipse([card_w // 2 - 30, 22, card_w // 2 + 30, 82], fill=accent)
        num = str(i + 1)
        nw, _ = _text_size(num, f_n)
        d.text(((card_w - nw) // 2, 26), num, font=f_n, fill=(255, 255, 255, 255))
        iw, _ = _text_size(item, f_i)
        d.text((max(16, (card_w - iw) // 2), 112), item, font=f_i, fill=TEXT)
        els.append({"img": card, "center": (x0 + i * (card_w + gap), H // 2 + 50),
                    "ease": ease_out_cubic, "rise": 50})
        if i < n - 1:  # 矢印
            arrow = Image.new("RGBA", (44, 40), (0, 0, 0, 0))
            d = ImageDraw.Draw(arrow)
            d.polygon([(4, 12), (26, 12), (26, 2), (42, 20), (26, 38), (26, 28),
                       (4, 28)], fill=(120, 130, 155, 255))
            els.append({"img": arrow,
                        "center": (x0 + i * (card_w + gap) + card_w // 2 + gap // 2,
                                   H // 2 + 50),
                        "ease": ease_out_cubic, "rise": 0})
    return els


_TEMPLATES = {
    "title_card": _el_title_card,
    "keyword_pop": _el_keyword_pop,
    "bullets": _el_bullets,
    "compare_cards": _el_compare_cards,
    "steps": _el_steps,
}


def has_display(display: dict) -> bool:
    return bool(display) and display.get("template") in _TEMPLATES


def _schedule(elements: list[dict], duration: float) -> None:
    """要素の登場をシーン尺に比例配分する(冒頭で出揃って残りが静止、を防ぐ)。

    最初の要素は0.15秒、最後の要素はシーンの約55%地点で登場開始。
    """
    n = len(elements)
    if n == 0:
        return
    window = max(0.0, duration * 0.55 - 0.15)
    for i, el in enumerate(elements):
        el["start"] = 0.15 + (window * i / max(1, n - 1) if n > 1 else 0.0)
        el["dur"] = 0.5


def render_frames(display: dict, bg_bytes: Optional[bytes], duration: float,
                  seed: int = 0, section: str = "") -> Iterator[bytes]:
    """シーン1本ぶんのRGB24フレーム列(ffmpegのstdinへ)。"""
    bg_big = build_background(bg_bytes).convert("RGBA")
    elements = _TEMPLATES[display["template"]](display, section, seed)
    _schedule(elements, duration)
    total = max(1, int(duration * FPS))
    max_dx = bg_big.width - W
    max_dy = bg_big.height - H
    forward = seed % 2 == 0
    for n in range(total):
        t = n / FPS
        f = n / max(1, total - 1)
        drift = f if forward else 1.0 - f
        dx = int(max_dx * drift)
        dy = int(max_dy * drift * 0.6)
        frame = bg_big.crop((dx, dy, dx + W, dy + H))
        for el in elements:
            p = el["ease"](_progress(t, el["start"], el["dur"]))
            cx, cy = el["center"]
            if el.get("rise"):
                cy = int(cy + el["rise"] * (1 - p))
            if el.get("slide"):
                cx = int(cx + el["slide"] * (1 - p))
            scale = (0.6 + 0.4 * p) if el.get("pop") else 1.0
            _paste_scaled(frame, el["img"], (cx, cy), scale, alpha=p)
        yield frame.convert("RGB").tobytes()
