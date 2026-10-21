#!/usr/bin/env python3
"""Tarjeta 1200x630 del caso Frontera Sur (nucleo) para RRSS.

Uso: /usr/bin/python3 gen_caso_frontera_card.py --api-json /tmp/caso.json --out /ruta/og-social.png
"""
from __future__ import annotations

import argparse
import json

from PIL import Image, ImageDraw, ImageFont

BG = (11, 18, 32)
PANEL = (19, 28, 47)
FG = (240, 244, 250)
MUTED = (166, 179, 196)
ACCENT = (255, 90, 31)
OK = (70, 200, 160)
LINE = (44, 58, 82)


def font(size, bold=False, serif=False):
    if serif:
        cands = ["/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"]
    elif bold:
        cands = ["/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    else:
        cands = ["/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    import os
    for c in cands:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-json", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    d = json.load(open(a.api_json, encoding="utf-8"))
    live = d.get("live", {})
    nucleo = live.get("nucleo", {})
    serie = live.get("serie_semanal_nucleo", [])
    delta = round(live.get("delta_pct", 0))
    top5 = live.get("amplificacion", {}).get("top5_pct")

    img = Image.new("RGB", (1200, 630), BG)
    overlay = Image.new("RGBA", (1200, 630), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for r in range(420, 0, -10):
        alpha = int(14 * (1 - r / 420) ** 2)
        od.ellipse([950 - r, -200 - r, 950 + r, -200 + r], fill=(255, 90, 31, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    dr = ImageDraw.Draw(img)

    dr.rectangle([0, 0, 10, 630], fill=ACCENT)
    dr.text((52, 36), "OBSERVATORIO DE AMPLIFICACIÓN · CASO FRONTERA SUR",
            font=font(20, True), fill=ACCENT)
    dr.text((52, 78), "Presión híbrida en la Frontera Sur",
            font=font(52, True, serif=True), fill=FG)
    dr.text((52, 146), "Ceuta y Marruecos · 30 jul – 21 oct 2026 · señal medida, no atribución",
            font=font(21), fill=MUTED)

    # tiles
    tiles = [
        (str(nucleo.get("eventos", "—")), "eventos en el núcleo"),
        (str(live.get("clusters_nucleo", "—")), "clusters del núcleo"),
        (f"+{delta} %", "vs media de 8 semanas"),
        (str(nucleo.get("autores", "—")), "autores distintos"),
    ]
    x0, y0, gap, tw, th = 52, 200, 14, 262, 110
    for i, (val, lab) in enumerate(tiles):
        x = x0 + i * (tw + gap)
        dr.rounded_rectangle([x, y0, x + tw, y0 + th], radius=13, fill=PANEL, outline=LINE, width=1)
        dr.text((x + 15, y0 + 14), val, font=font(34, True), fill=OK)
        dr.text((x + 15, y0 + 62), lab, font=font(16), fill=MUTED)

    # sparkline
    if serie:
        sx, sy, sw, sh = 52, 342, 1096, 170
        mx = max(serie) or 1
        pts = []
        for i, v in enumerate(serie):
            px = sx + sw * i / max(len(serie) - 1, 1)
            py = sy + sh - (sh * v / mx)
            pts.append((px, py))
        dr.line(pts, fill=ACCENT, width=4, joint="curve")
        for px, py in pts:
            dr.ellipse([px - 3, py - 3, px + 3, py + 3], fill=ACCENT)
        # media 8 sem (ultimas 8)
        media = live.get("media8_nucleo")
        if media is None and len(serie) >= 8:
            media = sum(serie[-8:-1]) / 7
        if media is not None:
            my = sy + sh - (sh * media / mx)
            for x in range(sx, sx + sw, 12):
                dr.line([(x, my), (x + 6, my)], fill=(255, 255, 255, 70), width=2)
            dr.text((sx, my - 26), ("media 8 sem: %.1f" % media).replace(".", ","), font=font(15), fill=MUTED)
        dr.text((sx, sy + sh + 10), "eventos del núcleo por semana · últimas 12",
                font=font(15), fill=MUTED)

    dr.text((52, 566), "fimi.viajeinteligencia.com/casos/frontera_sur_hibridos",
            font=font(20), fill=MUTED)
    dr.text((826, 566), "no atribuye actor ni confirma campaña", font=font(17), fill=(126, 140, 160))

    img.save(a.out, "PNG", optimize=True)
    print("ok", a.out, img.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
