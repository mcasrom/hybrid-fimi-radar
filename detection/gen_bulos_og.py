#!/usr/bin/env python3
"""gen_bulos_og.py — tarjeta social 1200x630 de "Posibles bulos contrastados".
Paleta CLARA (como las tarjetas de tema del dashboard): fondo blanco, borde suave,
numeros en color de acento. Lee data/radar.db (posible_bulos) -> /var/www/fimi/bulos-og.png.
"""
import sqlite3
import sys
from collections import Counter

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
FD = "/home/deploy/.local/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf"
BOLD = FD + "/DejaVuSans-Bold.ttf"
REG = FD + "/DejaVuSans.ttf"
BG = (255, 255, 255)
LINE = (226, 232, 240)
TILE = (248, 250, 252)
INK = (15, 23, 42)
SUB = (71, 85, 105)
MUT = (148, 163, 184)
LBL = (100, 116, 139)
ORANGE = (194, 65, 12)
RED = (220, 38, 38)
PURPLE = (124, 58, 237)
TEAL = (15, 118, 110)
AMBER = (217, 119, 6)


def F(path, size):
    return ImageFont.truetype(path, size)


def main():
    con = sqlite3.connect("/home/deploy/hybrid-fimi-radar/data/radar.db", timeout=30)
    rows = con.execute(
        "SELECT tema_id, cluster_label, banda, verifica_fuente, verifica_titulo"
        " FROM posible_bulos ORDER BY cycle_ts DESC, tema_id").fetchall()
    con.close()
    total = len(rows)
    clusters = len({r[1] for r in rows})
    high = sum(1 for r in rows if r[2] == "HIGH")
    anom = sum(1 for r in rows if r[2] == "ANOMALOUS")
    temas = Counter(r[0] for r in rows).most_common(4)
    fuentes = Counter(r[3] for r in rows)
    mx = max([n for _, n in temas] or [1])

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # barra de acento superior (estilo casa)
    d.rectangle([0, 0, W, 10], fill=ORANGE)
    # marco suave
    d.rounded_rectangle([24, 24, W - 24, H - 24], 16, outline=LINE, width=2)

    d.text((60, 56), "RADAR FIMI  ·  CONTRASTE CON VERIFICADORES", font=F(BOLD, 18), fill=ORANGE)
    d.text((60, 96), "Posibles bulos contrastados", font=F(BOLD, 50), fill=INK)
    d.text((60, 160), "Clusters en banda alta o anómala que comparten tema con una", font=F(REG, 18), fill=SUB)
    d.text((60, 184), "pieza reciente de Maldita o Newtral (14 días).", font=F(REG, 18), fill=SUB)

    def tile(x, y, w, h, val, label, color):
        d.rounded_rectangle([x, y, x + w, y + h], 12, fill=TILE, outline=LINE, width=2)
        d.text((x + w / 2, y + 44), str(val), font=F(BOLD, 50), fill=color, anchor="mm")
        d.text((x + w / 2, y + h - 20), label.upper(), font=F(REG, 14), fill=LBL, anchor="mm")

    tw, th, g = 270, 104, 20
    tile(60, 220, tw, th, total, "contrastes", ORANGE)
    tile(60 + tw + g, 220, tw, th, clusters, "clusters", TEAL)
    tile(60, 220 + th + g, tw, th, high, "banda HIGH", RED)
    tile(60 + tw + g, 220 + th + g, tw, th, anom, "ANOMALOUS", PURPLE)

    bx, by, bw = 690, 236, 450
    d.text((bx, by - 24), "CLUSTERS POR TEMA", font=F(BOLD, 15), fill=LBL)
    for i, (t, n) in enumerate(temas):
        yy = by + i * 40
        d.text((bx, yy), t, font=F(REG, 18), fill=SUB)
        d.rounded_rectangle([bx + 200, yy + 3, bx + 200 + bw - 240, yy + 21], 5, fill=(241, 245, 249))
        wpx = max(6, int((bw - 240) * n / mx))
        d.rounded_rectangle([bx + 200, yy + 3, bx + 200 + wpx, yy + 21], 5, fill=ORANGE)
        d.text((bx + bw - 8, yy), str(n), font=F(BOLD, 18), fill=INK, anchor="ra")

    d.rounded_rectangle([60, 452, 1140, 566], 12, fill=TILE, outline=LINE, width=2)
    d.text((84, 466), "LECTURA", font=F(BOLD, 15), fill=AMBER)
    pick = sorted(rows, key=lambda r: 0 if r[2] == "HIGH" else 1)[:2]
    for i, r in enumerate(pick):
        yy = 494 + i * 42
        d.ellipse([86, yy + 6, 96, yy + 16], fill=AMBER)
        tit = (r[4] or "").strip()
        if len(tit) > 80:
            tit = tit[:79] + "…"
        d.text((110, yy), tit, font=F(REG, 19), fill=SUB)
        d.text((110, yy + 21), f"{r[0]} · {r[2]} · {r[3]}", font=F(REG, 14), fill=MUT)

    d.text((60, 586), "Es contraste por tema, no veredicto: no atribuye actor ni confirma bulo.",
           font=F(BOLD, 17), fill=(154, 52, 18))
    ftxt = "  ·  ".join(f"{f}: {n}" for f, n in fuentes.most_common())
    d.text((60, 610), f"fimi.viajeinteligencia.com  ·  {total} contrastes · {clusters} clusters  ·  {ftxt}",
           font=F(REG, 14), fill=MUT)

    img.save("/var/www/fimi/bulos-og.png", "PNG", optimize=True)
    print("OK /var/www/fimi/bulos-og.png (claro)", img.size, "| total", total, "clusters", clusters)


if __name__ == "__main__":
    sys.exit(main())
