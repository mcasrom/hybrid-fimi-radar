#!/usr/bin/env python3
"""Tarjeta 1200x630 de la Consulta (FIMI)."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = (11, 18, 32)
PANEL = (19, 28, 47)
FG = (240, 244, 250)
MUTED = (166, 179, 196)
ACCENT = (255, 90, 31)
OK = (70, 200, 160)
LINE = (44, 58, 82)


def font(size, bold=False, serif=False):
    if serif:
        c = ["/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"]
    elif bold:
        c = ["/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    else:
        c = ["/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    import os
    for p in c:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
od = ImageDraw.Draw(ov)
for r in range(420, 0, -10):
    a = int(14 * (1 - r / 420) ** 2)
    od.ellipse([980 - r, -200 - r, 980 + r, -200 + r], fill=(255, 90, 31, a))
img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
d = ImageDraw.Draw(img)

d.rectangle([0, 0, 10, H], fill=ACCENT)
d.text((52, 34), "OBSERVATORIO DE AMPLIFICACIÓN", font=font(20, True), fill=ACCENT)
d.text((52, 72), "Consulta de enlaces", font=font(22), fill=MUTED)
d.text((52, 124), "¿Eco, feed o amplificación?", font=font(62, True, serif=True), fill=FG)
d.rectangle([54, 208, 190, 213], fill=ACCENT)
d.text((52, 232), "Pega un enlace y te doy la lectura en lenguaje llano.",
       font=font(25), fill=FG)

opts = [
    ("ECO DE PRENSA", "un medio y sus réplicas", (142, 197, 255)),
    ("FEED DE UNA FUENTE", "una cuenta dominante", (242, 201, 76)),
    ("AMPLIFICACIÓN", "varias cuentas, mismo contenido", OK),
]
y = 306
for titulo, sub, color in opts:
    d.rounded_rectangle([52, y, 800, y + 74], radius=14, fill=PANEL, outline=LINE, width=1)
    d.rounded_rectangle([72, y + 22, 82, y + 52], radius=4, fill=color)
    d.text((100, y + 14), titulo, font=font(23, True), fill=color)
    d.text((100, y + 44), sub, font=font(18), fill=MUTED)
    y += 84

d.text((52, 566), "fimi.viajeinteligencia.com/consulta.html", font=font(20), fill=MUTED)
d.text((800, 566), "sin atribución · sin cuenta", font=font(17), fill=(126, 140, 160))

img.save("/tmp/opencode/og-consulta.png", "PNG", optimize=True)
print("ok")
