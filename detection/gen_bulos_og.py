#!/usr/bin/env python3
"""gen_bulos_og.py — tarjeta social 1200x630 de "Posibles bulos contrastados".
Lee data/radar.db (posible_bulos) y escribe /var/www/fimi/bulos-og.png.
Contraste, no veredicto: no atribuye actor ni confirma bulo.
"""
import sqlite3
import sys
from collections import Counter

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
FD = "/home/deploy/.local/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf"
BOLD = FD + "/DejaVuSans-Bold.ttf"
REG = FD + "/DejaVuSans.ttf"
TOP, BOT = (11, 18, 32), (21, 35, 74)
CYAN, AMBER, PURPLE, TEAL = (56, 189, 248), (245, 158, 11), (167, 139, 250), (45, 212, 191)
WHITE, SLATE, MUT = (255, 255, 255), (203, 213, 225), (148, 163, 184)


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

    img = Image.new("RGB", (W, H), TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))

    d.text((60, 42), "RADAR FIMI  ·  CONTRASTE CON VERIFICADORES", font=F(BOLD, 18), fill=CYAN)
    d.text((60, 84), "Posibles bulos contrastados", font=F(BOLD, 50), fill=WHITE)
    d.text((60, 148), "Clusters en banda alta o anómala que comparten tema con una", font=F(REG, 18), fill=SLATE)
    d.text((60, 172), "pieza reciente de Maldita o Newtral (14 días).", font=F(REG, 18), fill=SLATE)

    def tile(x, y, w, h, val, label, color):
        d.rounded_rectangle([x, y, x + w, y + h], 14, fill=(12, 20, 38), outline=color, width=2)
        fv = F(BOLD, 50)
        d.text((x + w / 2, y + h / 2 - 6), str(val), font=fv, fill=color, anchor="mm")
        d.text((x + w / 2, y + h - 22), label, font=F(REG, 16), fill=SLATE, anchor="mm")

    tw, th, g = 270, 104, 20
    tile(60, 210, tw, th, total, "contrastes", CYAN)
    tile(60 + tw + g, 210, tw, th, clusters, "clusters", TEAL)
    tile(60, 210 + th + g, tw, th, high, "banda HIGH", AMBER)
    tile(60 + tw + g, 210 + th + g, tw, th, anom, "ANOMALOUS", PURPLE)

    # barras por tema (derecha)
    bx, by, bw = 690, 226, 450
    d.text((bx, by - 22), "CLUSTERS POR TEMA", font=F(BOLD, 15), fill=MUT)
    for i, (t, n) in enumerate(temas):
        yy = by + i * 40
        d.text((bx, yy), t, font=F(REG, 18), fill=SLATE)
        d.rounded_rectangle([bx + 200, yy + 3, bx + 200 + bw - 240, yy + 21], 5, fill=(30, 41, 59))
        wpx = max(6, int((bw - 240) * n / mx))
        d.rounded_rectangle([bx + 200, yy + 3, bx + 200 + wpx, yy + 21], 5, fill=CYAN)
        d.text((bx + bw - 8, yy), str(n), font=F(BOLD, 18), fill=WHITE, anchor="ra")

    # panel de lectura (2 contrastes)
    d.rounded_rectangle([60, 448, 1140, 574], 14, fill=(16, 26, 51), outline=(51, 65, 85), width=2)
    d.text((84, 462), "LECTURA", font=F(BOLD, 15), fill=(251, 191, 36))
    pick = sorted(rows, key=lambda r: 0 if r[2] == "HIGH" else 1)[:2]
    for i, r in enumerate(pick):
        yy = 490 + i * 44
        d.ellipse([86, yy + 6, 98, yy + 18], fill=(251, 191, 36))
        tit = (r[4] or "").strip()
        if len(tit) > 78:
            tit = tit[:77] + "…"
        d.text((112, yy), tit, font=F(REG, 19), fill=SLATE)
        d.text((112, yy + 22), f"{r[0]} · {r[2]} · {r[3]}", font=F(REG, 14), fill=MUT)

    d.text((60, 590), "Es contraste por tema, no veredicto: no atribuye actor ni confirma bulo.",
           font=F(BOLD, 18), fill=AMBER)
    ftxt = "  ·  ".join(f"{f}: {n}" for f, n in fuentes.most_common())
    d.text((60, 614), f"fimi.viajeinteligencia.com  ·  {total} contrastes · {clusters} clusters  ·  {ftxt}",
           font=F(REG, 14), fill=MUT)

    img.save("/var/www/fimi/bulos-og.png", "PNG", optimize=True)
    print("OK /var/www/fimi/bulos-og.png", img.size, "| total", total, "clusters", clusters)


if __name__ == "__main__":
    sys.exit(main())
