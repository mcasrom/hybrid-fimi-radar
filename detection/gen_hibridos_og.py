#!/usr/bin/env python3
"""gen_hibridos_og.py — Tarjeta OG 1200x630 del subcaso híbrido Frontera Sur.

Gráfico como protagonista: la serie real de 12 semanas del NÚCLEO dibujada
grande, con el pico etiquetado. Texto mínimo y legible (DejaVu real, NO el
bitmap por defecto). Datos del JSON live del caso; no inventa cifras.

Corre con /usr/bin/python3 (tiene PIL). Uso:
    /usr/bin/python3 detection/gen_hibridos_og.py [--out RUTA]
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

J = "/home/deploy/hybrid-fimi-radar/docs/casos/frontera_sur_hibridos.json"
OUT = "/var/www/fimi/casos/frontera_sur_hibridos/og.png"

FD = "/home/deploy/.local/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf"
if not os.path.exists(FD):
    FD = "/usr/share/fonts/truetype/liberation"
BOLD = os.path.join(FD, "DejaVuSans-Bold.ttf")
REG = os.path.join(FD, "DejaVuSans.ttf")
if not os.path.exists(BOLD):
    BOLD = os.path.join(FD, "LiberationSans-Bold.ttf")
    REG = os.path.join(FD, "LiberationSans-Regular.ttf")

W, H = 1200, 630
NAVY = (13, 27, 42)
NAVY2 = (20, 38, 56)
ACC = (234, 88, 12)
WHITE = (255, 255, 255)
SOFT = (198, 212, 228)
MUT = (126, 146, 168)


def F(path, size):
    return ImageFont.truetype(path, size)


def fit(dr, text, path, size, maxw):
    """Devuelve (fuente, ancho) reduciendo el tamaño hasta caber en maxw."""
    while size > 12:
        f = F(path, size)
        w = dr.textlength(text, font=f)
        if w <= maxw:
            return f, w
        size -= 2
    f = F(path, 12)
    return f, dr.textlength(text, font=f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    live = json.load(open(J, encoding="utf-8"))["live"]
    serie = [int(x) for x in live.get("serie_semanal_nucleo") or []]
    if len(serie) < 2:
        serie = [0, 0]
    ev = live.get("nucleo", {}).get("eventos")
    cls = live.get("clusters_nucleo")
    z = live.get("z_score")
    top5 = (live.get("amplificacion") or {}).get("top5_pct")
    vmax = max(serie) or 1

    img = Image.new("RGB", (W, H), NAVY)
    dr = ImageDraw.Draw(img)
    for i in range(H):
        f = i / H
        dr.line([(0, i), (W, i)],
                fill=tuple(int(NAVY[k] * (1 - f) + NAVY2[k] * f) for k in range(3)))

    dr.rectangle([0, 0, W, 9], fill=ACC)

    # ---- Cabecera (texto mínimo y grande) ----
    dr.text((64, 46), "OBSERVATORIO DE AMPLIFICACIÓN · CASO FRONTERA SUR",
            font=F(BOLD, 21), fill=ACC)
    title = "Presión híbrida en la Frontera Sur"
    ft, _ = fit(dr, title, BOLD, 58, W - 128)
    dr.text((64, 84), title, font=ft, fill=WHITE)
    dr.text((64, 158), "Núcleo de conversación · 12 semanas · señal, no atribución",
            font=F(REG, 23), fill=SOFT)

    # ---- Gráfico hero ----
    x0, x1 = 84, W - 84
    yt, yb = 218, 498
    n = len(serie)
    xs = [x0 + i * (x1 - x0) / (n - 1) for i in range(n)]
    scale = vmax * 1.18
    ys = [yb - (v / scale) * (yb - yt) for v in serie]

    # área bajo la curva
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    poly = [(xs[0], yb)] + list(zip(xs, ys)) + [(xs[-1], yb)]
    od.polygon(poly, fill=ACC + (70,))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    dr = ImageDraw.Draw(img)

    # media (referencia) + etiqueta
    mean = sum(serie) / n
    ym = yb - (mean / scale) * (yb - yt)
    for xx in range(x0, x1, 16):
        dr.line([(xx, ym), (min(xx + 8, x1), ym)], fill=(90, 108, 130), width=2)
    dr.text((x0 + 6, ym - 26), "media 12 sem", font=F(REG, 18), fill=MUT)

    # línea + puntos
    for i in range(n - 1):
        dr.line([(xs[i], ys[i]), (xs[i + 1], ys[i + 1])], fill=ACC, width=5)
    for i in range(n):
        r = 6
        dr.ellipse([xs[i] - r, ys[i] - r, xs[i] + r, ys[i] + r], fill=WHITE)
        dr.ellipse([xs[i] - r, ys[i] - r, xs[i] + r, ys[i] + r], outline=ACC, width=3)

    # pico (último punto) destacado + etiqueta grande
    if vmax >= 10:
        hi = ys.index(min(ys))
    else:
        hi = n - 1
    hx, hy = xs[hi], ys[hi]
    dr.ellipse([hx - 11, hy - 11, hx + 11, hy + 11], fill=WHITE, outline=ACC, width=5)
    lab = str(serie[hi])
    fl = F(BOLD, 44)
    lw = dr.textlength(lab, font=fl)
    lx = min(max(hx - lw / 2, x0), x1 - lw)
    dr.text((lx, hy - 62), lab, font=fl, fill=WHITE)
    sub = "esta semana" if hi == n - 1 else "pico"
    fs = F(REG, 19)
    sw = dr.textlength(sub, font=fs)
    dr.text((min(max(hx - sw / 2, x0), x1 - sw), hy - 16), sub,
            font=fs, fill=SOFT)

    # ---- Caption con KPIs reales ----
    partes = []
    if ev is not None:
        partes.append("%s eventos en el núcleo" % ev)
    if cls is not None:
        partes.append("%s clusters" % cls)
    if z is not None:
        partes.append("z-score pico %s" % z)
    if top5 is not None:
        partes.append("top-5 autores %s%%" % top5)
    dr.text((64, 522), " · ".join(partes), font=F(REG, 23), fill=SOFT)

    # ---- Pie ----
    dr.rectangle([0, H - 56, W, H], fill=NAVY2)
    dr.text((64, H - 40), "Señal medida ≠ coordinación confirmada · datos abiertos",
            font=F(REG, 19), fill=SOFT)
    url = "fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/"
    fu = F(BOLD, 18)
    uw = dr.textlength(url, font=fu)
    dr.text((W - 64 - uw, H - 40), url, font=fu, fill=WHITE)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    img.save(a.out, "PNG")
    print("OG ->", a.out, img.size)


if __name__ == "__main__":
    raise SystemExit(main())
