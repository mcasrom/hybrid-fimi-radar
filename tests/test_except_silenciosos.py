"""Guardarraíl contra errores silenciados (#3 deuda técnica).

Reglas (AGENTS): NUNCA `except: pass` sin log — ha ocultado bugs reales (ARI,
chips que no salían). Este test:
  - prohíbe los `except:` DESNUDOS (0 tolerados);
  - congela la deuda de `except ...: pass` en un BASELINE: no puede AUMENTAR.

Al arreglar uno de los 31 silenciosos (añadiendo log a stderr), baja el número
en el código y aquí. Escanea solo el código de producción (no tests/.venv).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = ["detection", "collectors", "normalizer", "clustering", "features", "scoring", "reports"]

# Deuda conocida a 23/Sep/2026. NO aumentar; bajar al ir arreglándolos.
BASELINE_SILENCIOSOS = 31


def _silencioso(body):
    for n in body:
        if isinstance(n, ast.Pass):
            continue
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            continue
        return False
    return True


def _scan():
    desnudos, silenciosos = [], []
    for d in DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    rel = f"{p.relative_to(ROOT)}:{node.lineno}"
                    if node.type is None:
                        desnudos.append(rel)
                    if _silencioso(node.body):
                        silenciosos.append(rel)
    return desnudos, silenciosos


def test_sin_except_desnudos():
    desnudos, _ = _scan()
    assert not desnudos, f"prohibido `except:` desnudo (usa `except Exception as e` + log): {desnudos}"


def test_no_aumentan_los_except_silenciosos():
    _, silenciosos = _scan()
    assert len(silenciosos) <= BASELINE_SILENCIOSOS, (
        f"except silenciosos={len(silenciosos)} > baseline={BASELINE_SILENCIOSOS}. "
        f"Añade un log a stderr en vez de `pass`: {silenciosos}")
