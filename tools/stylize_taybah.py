"""Restyle the TAYBAH_SERVICE reel: grade, branded frosted caption card, cream logo frames.

Usage: python stylize.py INPUT OUTPUT [--preview T1,T2,...]
"""

import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1072, 1920, 51
FONT_DIR = "/usr/share/fonts/opentype/inter/"

GREEN = (18, 62, 40)
GREEN_DARK = (9, 34, 22)
GOLD = (214, 172, 88)
WHITE = (255, 255, 255)

GRADE = (
    "eq=contrast=1.06:saturation=1.12:gamma=0.98,"
    "colorbalance=rs=0.03:gs=0.0:bs=-0.03:rm=0.02:bm=-0.02:rh=0.015:bh=-0.02"
)

# Logo crossfades measured on the source (logo weight 1 -> 0 and 0 -> 1).
INTRO_FADE = (0.735, 1.245)
OUTRO_FADE = (30.12, 30.625)
BAND_TOP, BAND_BOTTOM = 421, 1500  # cream band of the logo frames

# Frosted card covering the original burned-in captions (x 139..930, y 1440..1695).
CARD = (52, 1400, 1020, 1738)
CARD_RADIUS = 36
CARD_IN = (0.72, 1.12)
CARD_OUT = (30.08, 30.4)

# (text in, text out, kicker, main with *highlight*, sub)
SEGMENTS = [
    (1.00, 8.95, "РАЗДАЧА ФИНИКОВ", "Каждый финик —|это ваша *садака*", None),
    (9.30, 16.65, "РАЗДАЧА ВОДЫ", "Каждая капля воды в эту жару —|это ваша *награда*", None, 50),
    (16.90, 20.05, "ПОСАДКА ПАЛЬМ", "Каждое дерево — это ваш *след*", None),
    (20.45, 24.25, "СОВЕРШЕНИЕ УМРЫ", "Каждая Умра —|это *свет* для ваших близких", None),
    (24.75, 30.05, "TAYBAH_SERVICE", "Ваша садака —|в самом *святом* *месте*",
     "Ваш мост к добру в священных городах"),
]
OUTRO_TAGLINE_IN = 30.7


def font(name, size):
    return ImageFont.truetype(FONT_DIR + name, size)


F_KICKER = font("Inter-SemiBold.otf", 29)
F_MAIN = font("InterDisplay-SemiBold.otf", 56)
F_SUB = font("Inter-Medium.otf", 33)
F_TAG = font("InterDisplay-SemiBold.otf", 56)


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def ramp(t, a, b):
    return min(max((t - a) / (b - a), 0.0), 1.0)


# ------------------------------------------------------------ pre-rendering


def rounded_mask(size, radius, scale=4):
    w, h = size
    big = Image.new("L", (w * scale, h * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius * scale, fill=255)
    return big.resize(size, Image.LANCZOS)


CARD_W, CARD_H = CARD[2] - CARD[0], CARD[3] - CARD[1]
CARD_MASK = rounded_mask((CARD_W, CARD_H), CARD_RADIUS)


def card_tint():
    """Green gradient tint + gold hairline border + soft top sheen (RGBA)."""
    y = np.linspace(0, 1, CARD_H)[:, None]
    rgb = np.array(GREEN) * (1 - y) + np.array(GREEN_DARK) * y
    alpha = 0.66 + 0.14 * y
    tint = np.dstack([np.broadcast_to(rgb[:, i:i+1], (CARD_H, CARD_W)) for i in range(3)]
                     + [np.broadcast_to(alpha * 255, (CARD_H, CARD_W))]).astype(np.uint8)
    img = Image.fromarray(tint, "RGBA")
    scale = 4
    border = Image.new("RGBA", (CARD_W * scale, CARD_H * scale), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (3, 3, CARD_W * scale - 4, CARD_H * scale - 4), CARD_RADIUS * scale - 3,
        outline=GOLD + (150,), width=2 * scale)
    img.alpha_composite(border.resize((CARD_W, CARD_H), Image.LANCZOS))
    return img


TINT = card_tint()


def text_sprite(text, fnt, color, tracking=0, shadow=True):
    """Render text with optional letter spacing and a soft shadow."""
    if tracking:
        width = sum(fnt.getlength(ch) for ch in text) + tracking * (len(text) - 1)
    else:
        width = fnt.getlength(text)
    ascent, descent = fnt.getmetrics()
    pad = 16
    w, h = int(width) + pad * 2, ascent + descent + pad * 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    def draw_text(d, fill):
        if tracking:
            x = pad
            for ch in text:
                d.text((x, pad), ch, font=fnt, fill=fill)
                x += fnt.getlength(ch) + tracking
        else:
            d.text((pad, pad), text, font=fnt, fill=fill)

    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_text(ImageDraw.Draw(sh), (0, 0, 0, 150))
        sh = sh.filter(ImageFilter.GaussianBlur(5))
        layer.alpha_composite(sh, (0, 3))
    draw_text(draw, color + (255,))
    return layer, pad, width


def layout_words(text, fnt, max_width, highlight_color):
    """Split into lines; return list of lines, each a list of (sprite, x_offset_in_line).

    "|" forces a line break; otherwise lines are wrapped and balanced automatically.
    """
    if "|" in text:
        return [line for part in text.split("|") for line in layout_words(part, fnt, max_width, highlight_color)]
    words = []
    for raw in text.split():
        hl = raw.startswith("*") and raw.endswith("*")
        words.append((raw.strip("*"), hl))
    space = fnt.getlength(" ")
    lines, current, cur_w = [], [], 0.0
    for word, hl in words:
        ww = fnt.getlength(word)
        if current and cur_w + space + ww > max_width:
            lines.append(current)
            current, cur_w = [], 0.0
        cur_w += (space if current else 0) + ww
        current.append((word, hl))
    if current:
        lines.append(current)
    # balance two lines: move words from the first line to the second while it helps
    if len(lines) == 2:
        while len(lines[0]) > 1:
            w0 = fnt.getlength(" ".join(w for w, _ in lines[0][:-1]))
            w1 = fnt.getlength(" ".join(w for w, _ in [lines[0][-1]] + lines[1]))
            if w1 > max_width or w1 > fnt.getlength(" ".join(w for w, _ in lines[0])):
                break
            lines[1].insert(0, lines[0].pop())
            if w0 < w1:
                break
    result = []
    for line in lines:
        items, x = [], 0.0
        for word, hl in line:
            sprite, pad, ww = text_sprite(word, fnt, highlight_color if hl else WHITE)
            items.append((sprite, pad, x))
            x += ww + space
        result.append((items, x - space))
    return result


class Segment:
    def __init__(self, t_in, t_out, kicker, main, sub, main_size=56):
        self.t_in, self.t_out = t_in, t_out
        self.kicker = text_sprite(kicker, F_KICKER, GOLD, tracking=5, shadow=False)
        self.lines = layout_words(main, font("InterDisplay-SemiBold.otf", main_size), CARD_W - 90, GOLD)
        self.sub = text_sprite(sub, F_SUB, (232, 222, 200)) if sub else None

        line_h = 70
        kicker_h = 36
        sub_h = 46 if sub else 0
        total = kicker_h + 22 + line_h * len(self.lines) + (14 + sub_h if sub else 0)
        top = (CARD_H - total) / 2
        self.kicker_y = top
        self.lines_y = top + kicker_h + 22
        self.line_h = line_h
        self.sub_y = self.lines_y + line_h * len(self.lines) + 20

    def draw(self, layer, t, card_dy):
        if t < self.t_in or t > self.t_out + 0.3:
            return
        out = 1 - ramp(t, self.t_out, self.t_out + 0.25)
        cx = CARD_W / 2

        # kicker with gold rules on both sides
        a = ease_out(ramp(t, self.t_in, self.t_in + 0.35)) * out
        sprite, pad, width = self.kicker
        x = cx - width / 2
        y = self.kicker_y + card_dy + (1 - a) * 10
        paste(layer, sprite, x - pad, y - pad, a)
        rule_len = 44 * a
        mid = y + 19
        d = ImageDraw.Draw(layer)
        fill = GOLD + (int(200 * a),)
        d.line((x - 18 - rule_len, mid, x - 18, mid), fill=fill, width=2)
        d.line((x + width + 18, mid, x + width + 18 + rule_len, mid), fill=fill, width=2)

        # main text: word-by-word rise
        k = 0
        for li, (items, line_w) in enumerate(self.lines):
            x0 = cx - line_w / 2
            y0 = self.lines_y + li * self.line_h + card_dy
            for sprite, pad, wx in items:
                start = self.t_in + 0.15 + 0.07 * k
                a = ease_out(ramp(t, start, start + 0.4)) * out
                paste(layer, sprite, x0 + wx - pad, y0 - pad + (1 - a) * 16, a)
                k += 1

        if self.sub:
            sprite, pad, width = self.sub
            start = self.t_in + 0.25 + 0.07 * k
            a = ease_out(ramp(t, start, start + 0.45)) * out
            paste(layer, sprite, cx - width / 2 - pad, self.sub_y + card_dy - pad + (1 - a) * 10, a)


def paste(layer, sprite, x, y, alpha):
    if alpha <= 0.003:
        return
    if alpha < 0.999:
        sprite = sprite.copy()
        sprite.putalpha(sprite.getchannel("A").point(lambda v: int(v * alpha)))
    layer.alpha_composite(sprite, (int(round(x)), int(round(y))))


SEGS = [Segment(*s) for s in SEGMENTS]

TAG_LINES = [text_sprite(s, F_TAG, GREEN, shadow=False) for s in ("Ваш мост к добру", "в священных городах")]


# ---------------------------------------------------------------- per frame


def logo_weight(t):
    if t <= INTRO_FADE[1]:
        return 1 - ramp(t, *INTRO_FADE)
    return ramp(t, *OUTRO_FADE)


def process(frame: np.ndarray, t: float, cream: np.ndarray) -> np.ndarray:
    out = frame

    # 1) Fill the black letterbox bars of the logo frames with the band's cream.
    a = logo_weight(t)
    if a > 0:
        out = out.astype(np.float32)
        for y0, y1 in ((0, BAND_TOP), (BAND_BOTTOM, H)):
            out[y0:y1] += a * cream  # bars are black, so adding a*cream is exact
        out = np.clip(out, 0, 255).astype(np.uint8)

    img = Image.fromarray(out, "RGB")

    # 2) Frosted caption card.
    card_a = ease_out(ramp(t, *CARD_IN)) * (1 - ramp(t, *CARD_OUT))
    if card_a > 0:
        dy = int(round((1 - card_a) * 26))
        box = (CARD[0], CARD[1], CARD[2], CARD[3])
        crop = img.crop(box)
        small = crop.resize((CARD_W // 4, CARD_H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(7))
        frosted = small.resize((CARD_W, CARD_H), Image.BICUBIC).convert("RGBA")
        frosted.alpha_composite(TINT)
        layer = frosted
        for seg in SEGS:
            seg.draw(layer, t, 0)
        mask = CARD_MASK.point(lambda v: int(v * card_a)) if card_a < 0.999 else CARD_MASK
        # soft drop shadow below the card
        img.paste(layer.convert("RGB"), (CARD[0], CARD[1] + dy), mask)

    # 3) Outro tagline on the cream area under the logo.
    ta = ease_out(ramp(t, OUTRO_TAGLINE_IN, OUTRO_TAGLINE_IN + 0.5))
    if ta > 0:
        rgba = img.convert("RGBA")
        y = 1580
        d = ImageDraw.Draw(rgba)
        half = 70 * ta
        d.line((W / 2 - half, y, W / 2 + half, y), fill=(193, 148, 61, int(255 * ta)), width=3)
        for i, (sprite, pad, width) in enumerate(TAG_LINES):
            paste(rgba, sprite, W / 2 - width / 2 - pad, y + 30 + i * 70 - pad + (1 - ta) * 14, ta)
        img = rgba.convert("RGB")

    return np.asarray(img)


def decode(path, extra=()):
    return subprocess.Popen(
        ["ffmpeg", "-v", "error", *extra, "-i", path, "-vf", GRADE, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    preview = None
    if len(sys.argv) > 3 and sys.argv[3] == "--preview":
        preview = [float(x) for x in sys.argv[4].split(",")]

    # Cream colour of the (graded) logo band, used to fill the bars.
    first = decode(src).stdout.read(W * H * 3)
    f0 = np.frombuffer(first, np.uint8).reshape(H, W, 3)
    cream = f0[BAND_TOP + 10:BAND_TOP + 60, 5:60].reshape(-1, 3).mean(0).astype(np.float32)
    print("cream", cream)

    if preview:
        for t in preview:
            proc = decode(src, ["-ss", str(t)])
            raw = proc.stdout.read(W * H * 3)
            proc.kill()
            frame = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
            Image.fromarray(process(frame, t, cream)).save(f"{dst}_{t:05.2f}.png")
        return

    dec = decode(src)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", src, "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", "-shortest", dst],
        stdin=subprocess.PIPE)
    i = 0
    while True:
        raw = dec.stdout.read(W * H * 3)
        if len(raw) < W * H * 3:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
        enc.stdin.write(process(frame, i / FPS, cream).tobytes())
        i += 1
        if i % 200 == 0:
            print("frame", i, flush=True)
    enc.stdin.close()
    enc.wait()
    print("done", i, "frames")


if __name__ == "__main__":
    main()
