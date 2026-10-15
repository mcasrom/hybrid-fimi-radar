#!/usr/bin/env python3
"""gen_hibridos_og.py — Tarjeta OG 1200x630 del subcaso híbrido Frontera Sur.
Lee docs/casos/frontera_sur_hibridos.json (live) y dibuja la tarjeta social."""
import json
from PIL import Image, ImageDraw, ImageFont

J = "/home/deploy/hybrid-fimi-radar/docs/casos/frontera_sur_hibridos.json"
OUT = "/var/www/fimi/casos/frontera_sur_hibridos/og.png"
NAVY, ACC, WHT, MUT = (13, 27, 42), (193, 68, 14), (255, 255, 255), (201, 214, 226)
d = json.load(open(J, encoding="utf-8"))["live"]


def F(sz, b=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if b else "")
    try:
        return ImageFont.truetype(p, sz)
    except OSError:
        return ImageFont.load_default()


W, H = 1200, 630
img = Image.new("RGB", (W, H), NAVY)
dr = ImageDraw.Draw(img)
dr.rectangle([60, 70, 70, H - 70], fill=ACC)
dr.text((105, 75), "Observatorio de amplificación", font=F(30), fill=ACC)
dr.text((105, 125), "Indicadores de presión híbrida", font=F(54, True), fill=WHT)
dr.text((105, 192), "en Frontera Sur (Marruecos)", font=F(54, True), fill=WHT)

nuc = d.get("nucleo", {})
kpis = [("clusters núcleo", d.get("clusters_nucleo")),
        ("eventos núcleo", nuc.get("eventos")),
        ("z-score pico", d.get("z_score")),
        ("top-5 autores", "%s%%" % d.get("amplificacion", {}).get("top5_pct"))]
x = 105
for lbl, val in kpis:
    dr.text((x, 320), str(val), font=F(60, True), fill=ACC)
    dr.text((x, 395), lbl, font=F(24), fill=MUT)
    x += 260
dr.line([105, 480, W - 105, 480], fill=(60, 80, 105), width=2)
dr.text((105, 505), "Señal, no atribución. Pico de conversación con baja", font=F(26), fill=MUT)
dr.text((105, 540), "corroboración y sin evidencia de coordinación por URLs.", font=F(26), fill=MUT)
dr.text((105, 585), "fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/", font=F(22), fill=ACC)
img.save(OUT, "PNG")
print("OG ->", OUT)
