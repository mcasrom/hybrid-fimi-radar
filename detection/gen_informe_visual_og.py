#!/usr/bin/env python3
"""gen_informe_visual_og.py — OG 1200x630 (navy) para cada informe visual de tema.

Lee data/radar.db (clusters) y escribe /var/www/fimi/informes/visual/og-<tema>.png.
Determinista, PIL. Corre con /usr/bin/python3 (como gen_bulos_og.py).
Uso: /usr/bin/python3 detection/gen_informe_visual_og.py --todos
"""
import argparse
import os
import sqlite3

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
DB = "/home/deploy/hybrid-fimi-radar/data/radar.db"
OUT = "/var/www/fimi/informes/visual"
FD = "/home/deploy/.local/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf"
BOLD = FD + "/DejaVuSans-Bold.ttf"
REG = FD + "/DejaVuSans.ttf"
NAVY = (30, 58, 95)
NAVY2 = (23, 46, 77)
WHITE = (255, 255, 255)
SOFT = (205, 216, 233)
ACCENT = (234, 88, 12)
TILE = (255, 255, 255)
ACTIVOS = ["frontera_sur", "oriente_medio", "elecciones", "inteligencia_artificial",
           "eeuu_politica", "sahel", "energia", "defensa_espana", "espana_elecciones"]
NOMBRES = {
    "frontera_sur": "Frontera Sur (España–Marruecos)",
    "oriente_medio": "Oriente Medio",
    "elecciones": "Elecciones (panorama internacional)",
    "inteligencia_artificial": "Inteligencia artificial",
    "eeuu_politica": "EE. UU. — política",
    "sahel": "Sahel",
    "energia": "Energía",
    "defensa_espana": "España — defensa y amenazas híbridas",
    "espana_elecciones": "España — elecciones generales",
}


def F(path, size):
    return ImageFont.truetype(path, size)


def wrap(d, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def kpis(con, tema):
    n = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (tema,)).fetchone()[0]
    alta = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=? AND overall_score>=60", (tema,)).fetchone()[0]
    au = con.execute(
        "SELECT COUNT(DISTINCT ce.author) FROM cluster_events ce JOIN clusters c"
        " ON c.id=ce.cluster_id WHERE c.tema_id=?", (tema,)).fetchone()[0]
    return n, alta, au


def render(con, tema, nombre):
    n, alta, au = kpis(con, tema)
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    # degradado vertical suave
    for y in range(H):
        f = y / H
        c = tuple(int(NAVY[i] * (1 - f) + NAVY2[i] * f) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    d.rectangle([0, 0, W, 12], fill=ACCENT)
    d.text((64, 60), "OBSERVATORIO DE AMPLIFICACION  ·  INFORME VISUAL", font=F(BOLD, 19), fill=ACCENT)
    lines = wrap(d, nombre, F(BOLD, 56), W - 128)
    y = 104
    for ln in lines[:2]:
        d.text((64, y), ln, font=F(BOLD, 56), fill=WHITE)
        y += 66
    d.text((64, y + 8), "Que se observa, senales, hipotesis alternativas y limites.", font=F(REG, 22), fill=SOFT)
    # tiles KPI
    ty = 360
    tw, th, gap = 240, 118, 22
    x = 64
    for val, lab in [(n, "clusters"), (au, "cuentas en clusters"), (alta, "en banda alta")]:
        d.rounded_rectangle([x, ty, x + tw, ty + th], 14, fill=TILE)
        d.text((x + 26, ty + 20), str(val), font=F(BOLD, 46), fill=NAVY)
        d.text((x + 26, ty + 78), lab, font=F(REG, 18), fill=(71, 85, 105))
        x += tw + gap
    # pie
    d.rectangle([0, H - 62, W, H], fill=NAVY2)
    d.text((64, H - 42), "Senal detectada != desinformacion confirmada != atribucion de actor.",
           font=F(REG, 17), fill=SOFT)
    url = "fimi.viajeinteligencia.com/informes/visual/"
    uw = d.textlength(url, font=F(BOLD, 17))
    d.text((W - 64 - uw, H - 42), url, font=F(BOLD, 17), fill=WHITE)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    temas = ACTIVOS if a.todos else ([a.tema] if a.tema else [])
    if not temas:
        print("indica --tema o --todos")
        return 2
    os.makedirs(a.out, exist_ok=True)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    for tema in temas:
        img = render(con, tema, NOMBRES.get(tema, tema))
        p = os.path.join(a.out, "og-%s.png" % tema)
        img.save(p)
        print("OK:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
