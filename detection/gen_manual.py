#!/usr/bin/env python3
"""gen_manual.py — genera el Manual de Operacion (PDF) desde Markdown versionado.

Fuente: docs/manual/manifest.json + los .md que lista (docs/*.md del repo).
Salida: /var/www/fimi/manual-fimi-<tag>.pdf y /var/www/fimi/manual.pdf.

Reglas: no se edita el PDF a mano; se edita el Markdown y se regenera. Requiere
fpdf2 (requirements.txt) y las fuentes DejaVu (matplotlib). Sin emojis (los mapas
a texto), sin HTML externo.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "docs", "manual", "manifest.json")
OUT_DIR = "/var/www/fimi"
FONT_DIR = "/home/deploy/.local/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf"
ACCENT = (194, 65, 12)
INK = (30, 41, 59)
MUT = (100, 116, 139)
LH = 6.0
SIZE = 10.5

TOKEN = re.compile(r"(\*\*.+?\*\*|__.+?__|`[^`]+`|\*[^*\n]+?\*|\[[^\]]+\]\([^)]+\))")


def clean(s: str) -> str:
    s = (s.replace("\u2705", "OK").replace("\u26a0\ufe0f", "!").replace("\u26a0", "!")
         .replace("\u2764", "").replace("\u2615", "").replace("\U0001f4e1", ""))
    out = []
    for ch in s:
        o = ord(ch)
        if o in (0x200d, 0xfe0f, 0xfe0e):
            continue
        if 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF:
            continue
        out.append(ch)
    return "".join(out)


def version() -> str:
    try:
        return subprocess.check_output(["git", "-C", ROOT, "describe", "--tags", "--always"],
                                       text=True).strip()
    except Exception:
        return "v0.2"


class Manual(FPDF):
    def __init__(self, ver: str):
        super().__init__(format="A4")
        self.ver = ver
        self.set_auto_page_break(True, margin=18)
        self.set_margins(20, 18, 20)
        self.add_font("DV", "", os.path.join(FONT_DIR, "DejaVuSans.ttf"))
        self.add_font("DV", "B", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"))
        self.add_font("DV", "I", os.path.join(FONT_DIR, "DejaVuSans-Oblique.ttf"))
        self.add_font("DV", "BI", os.path.join(FONT_DIR, "DejaVuSans-BoldOblique.ttf"))
        self.add_font("DVM", "", os.path.join(FONT_DIR, "DejaVuSansMono.ttf"))
        self.set_font("DV", "", SIZE)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("DV", "", 7.5)
        self.set_text_color(*MUT)
        self.cell(0, 5, "Manual de Operacion - Observatorio de amplificacion (FIMI)",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(226, 232, 240)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)
        self.set_text_color(*INK)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font("DV", "", 7.5)
        self.set_text_color(*MUT)
        self.cell(0, 6, f"{self.ver}  ·  CC BY 4.0 (datos) · AGPL-3.0 (codigo)"
                        f"                                                                 {self.page_no()}",
                  align="C")
        self.set_text_color(*INK)


def render_par(pdf, text, size=SIZE, indent=0.0, style=""):
    lh = LH * (size / SIZE)
    pdf.set_font("DV", style, size)
    if indent:
        pdf.set_x(pdf.l_margin + indent)
    for tok in TOKEN.split(text):
        if not tok:
            continue
        if (tok.startswith("**") and tok.endswith("**")) or (tok.startswith("__") and tok.endswith("__")):
            pdf.set_font("DV", "BI" if "I" in style else "B", size)
            pdf.write(lh, clean(tok[2:-2]))
            pdf.set_font("DV", style, size)
        elif tok.startswith("`") and tok.endswith("`"):
            pdf.set_font("DVM", "", size - 1)
            pdf.write(lh, clean(tok[1:-1]))
            pdf.set_font("DV", style, size)
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            pdf.set_font("DV", "BI" if "B" in style else "I", size)
            pdf.write(lh, clean(tok[1:-1]))
            pdf.set_font("DV", style, size)
        elif tok.startswith("["):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok)
            if m:
                pdf.set_text_color(*ACCENT)
                pdf.write(lh, clean(m.group(1)))
                pdf.set_text_color(*INK)
            else:
                pdf.write(lh, clean(tok))
        else:
            pdf.write(lh, clean(tok))
    pdf.ln(lh * 1.05)


def render_heading(pdf, txt, lvl):
    pdf.ln(2)
    if lvl <= 2:
        pdf.set_font("DV", "B", 14)
        pdf.set_text_color(*ACCENT)
    elif lvl == 3:
        pdf.set_font("DV", "B", 12)
        pdf.set_text_color(*INK)
    else:
        pdf.set_font("DV", "B", 10.5)
        pdf.set_text_color(*INK)
    pdf.multi_cell(0, 7, clean(txt), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.ln(1)


def render_code(pdf, lines):
    pdf.set_font("DVM", "", 8.2)
    pdf.set_fill_color(245, 247, 250)
    for ln in lines:
        pdf.multi_cell(0, 4.6, clean(ln) or " ", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_font("DV", "", SIZE)


def render_quote(pdf, text):
    pdf.set_text_color(*MUT)
    render_par(pdf, text, size=9.6, indent=6, style="I")
    pdf.set_text_color(*INK)


def render_list(pdf, items, ordered=False):
    for i, it in enumerate(items, 1):
        bullet = f"{i}." if ordered else "\u2022"
        pdf.set_font("DV", "", SIZE)
        pdf.set_x(pdf.l_margin + 3)
        pdf.cell(6, LH, clean(bullet))
        render_par(pdf, it)


def render_table(pdf, rows):
    data = []
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != ""):
            continue  # fila separadora
        data.append([re.sub(r"[*`]", "", c) for c in cells])
    if not data:
        return
    try:
        pdf.set_font("DV", "", 8.6)
        with pdf.table(line_height=5.2, text_align="LEFT", width=pdf.epw) as t:
            for row in data:
                tr = t.row()
                for c in row:
                    tr.cell(clean(c))
        pdf.ln(3)
    except Exception as e:
        print(f"  aviso tabla ({e}); se pinta como lineas", file=sys.stderr)
        for row in data:
            render_par(pdf, " | ".join(row), size=8.6)


def render_md(pdf, text):
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):  # el titulo lo pone el capitulo
        i += 1
    while i < len(lines):
        s = lines[i].rstrip()
        if not s.strip():
            i += 1
            continue
        if s.lstrip().startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            render_code(pdf, buf)
            continue
        if re.match(r"^#{1,6}\s", s):
            lvl = len(s) - len(s.lstrip("#"))
            render_heading(pdf, s[lvl:].strip(), lvl)
            i += 1
            continue
        if re.match(r"^\s*([-*_]\s*){3,}$", s):
            pdf.ln(1)
            pdf.set_draw_color(226, 232, 240)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(3)
            i += 1
            continue
        if s.lstrip().startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            render_quote(pdf, " ".join(buf))
            continue
        if s.lstrip().startswith("|") and "|" in s:
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                buf.append(lines[i])
                i += 1
            render_table(pdf, buf)
            continue
        if re.match(r"^\s*[-*+]\s", s):
            buf = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s", lines[i]):
                buf.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]).rstrip())
                i += 1
            render_list(pdf, buf)
            continue
        if re.match(r"^\s*\d+[.)]\s", s):
            buf = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s", lines[i]):
                buf.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]).rstrip())
                i += 1
            render_list(pdf, buf, ordered=True)
            continue
        buf = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|>|\||```)", lines[i]):
            buf.append(lines[i].rstrip())
            i += 1
        render_par(pdf, " ".join(buf))


def render_toc(pdf, outline):
    pdf.set_font("DV", "B", 16)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 12, "\u00cdndice", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    for sec in outline:
        lvl = getattr(sec, "level", 0)
        pg = str(getattr(sec, "page_number", ""))
        pdf.set_font("DV", "B" if lvl == 0 else "", 11 if lvl == 0 else 9.5)
        pdf.set_text_color(*INK if lvl == 0 else MUT)
        w = pdf.epw - pdf.get_string_width(pg) - 4
        pdf.cell(w, 7.5, clean(sec.name), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(0, 7.5, pg, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)


def cover(pdf, ver, fecha):
    pdf.add_page()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, pdf.w, 46, style="F")
    pdf.set_y(16)
    pdf.set_font("DV", "B", 15)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, "OBSERVATORIO DE AMPLIFICACI\u00d3N - \u00c1MBITO FIMI", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DV", "", 10)
    pdf.cell(0, 8, "fimi.viajeinteligencia.com", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(70)
    pdf.set_text_color(*INK)
    pdf.set_font("DV", "B", 30)
    pdf.multi_cell(0, 14, "Manual de Operaci\u00f3n", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DV", "", 13)
    pdf.set_text_color(*MUT)
    pdf.multi_cell(0, 8, "Qu\u00e9 mide, c\u00f3mo lo mide, c\u00f3mo se gobierna, "
                         "se valida y se opera", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(8)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("DV", "", 10.5)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 6, f"Versi\u00f3n: {ver}\nGenerado: {fecha}\n"
                         "Autor: Miguel Castillo\n"
                         "Datos: CC BY 4.0  ·  Software: AGPL-3.0\n"
                         "Repositorio: github.com/mcasrom/hybrid-fimi-radar",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(-28)
    pdf.set_font("DV", "I", 8.5)
    pdf.set_text_color(*MUT)
    pdf.multi_cell(0, 5, "Encuadre: el Observatorio mide amplificaci\u00f3n, no coordinaci\u00f3n "
                         "confirmada ni autor\u00eda. Una banda alta no es una campa\u00f1a probada.",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def main():
    ver = version()
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    man = json.load(open(MANIFEST, encoding="utf-8"))
    pdf = Manual(ver)
    cover(pdf, ver, fecha)
    pdf.add_page()
    pdf.insert_toc_placeholder(render_toc, pages=1)
    for idx, cap in enumerate(man["capitulos"]):
        if idx > 0:
            pdf.add_page()
        pdf.start_section(cap["titulo"], level=0)
        pdf.set_font("DV", "B", 18)
        pdf.set_text_color(*ACCENT)
        pdf.multi_cell(0, 11, clean(cap["titulo"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        pdf.set_text_color(*INK)
        for src in cap["fuentes"]:
            fp = os.path.join(ROOT, src)
            if not os.path.exists(fp):
                print(f"  aviso: falta {src}", file=sys.stderr)
                continue
            render_md(pdf, open(fp, encoding="utf-8").read())
            pdf.ln(2)
        print(f"  capitulo: {cap['titulo']}")
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"manual-fimi-{ver.split('-')[0]}.pdf")
    pdf.output(out)
    pdf.output(os.path.join(OUT_DIR, "manual.pdf"))
    print(f"OK {out} ({pdf.pages_count} paginas) + manual.pdf")


if __name__ == "__main__":
    raise SystemExit(main())
