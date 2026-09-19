import pathlib

p = pathlib.Path("/home/deploy/hybrid-fimi-radar/detection/elecciones.py")
s = p.read_text(encoding="utf-8")

old = '''_BAND_COL = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "ANOMALOUS": "#d97706",
_GREEN = "22c55e"
_GREY = "94a3b8"

             "WATCH": "#0e7490", "NORMAL": "#64748b"}
'''
new = '''_BAND_COL = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "ANOMALOUS": "#d97706",
             "WATCH": "#0e7490", "NORMAL": "#64748b"}

_GREEN = "22c55e"
_GREY = "94a3b8"
'''

n = s.count(old)
print("ocurrencias del bloque roto:", n)
assert n == 1, "esperado exactamente 1 ocurrencia"
s2 = s.replace(old, new)
p.write_text(s2, encoding="utf-8")
print("v4 aplicado OK")