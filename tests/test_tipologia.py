"""Tests de la tipologia estructural de clusters (detection/tipologia.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detection.tipologia import _boilerplate, rasgos, tipo_de  # noqa: E402


def _ev(ts, author, url, text):
    return {"ts": ts, "author": author, "url": url, "text": text}


def test_boilerplate_detecta_pie_repetido():
    pie = "🤖 IA: No es clickbait ✅ 👥 Usuarios: No es clickbait ✅"
    textos = [f"Titular {i} sobre el conflicto\n\n{pie}" for i in range(4)]
    bp = _boilerplate(textos)
    assert bp is not None
    assert bp[1] >= 0.5


def test_boilerplate_none_sin_repeticion():
    textos = ["una noticia completamente distinta sobre economia",
              "otra cosa sin relacion alguna de deportes y cultura",
              "un tercer texto del todo diferente sobre ciencia"]
    assert _boilerplate(textos) is None


def test_tipo_red_dominio_unico():
    evs = [_ev(1000 + i, f"u{i}.bsky.social", f"https://uno.example/a{i}", f"texto {i}")
           for i in range(3)]
    r = rasgos(evs)
    tipo, flags, _ = tipo_de(r)
    assert tipo == "red_dominio_unico"
    assert "red_dominio_unico" in flags


def test_tipo_automatizado_plantilla():
    pie = "marca de la casa repetida en todas las publicaciones del canal"
    evs = [_ev(1000 + i, f"bot{i}.bsky.social", f"https://bot.example/{i}",
               f"Noticia numero {i}\n\n{pie}") for i in range(4)]
    r = rasgos(evs)
    tipo, flags, _ = tipo_de(r)
    assert tipo == "automatizado_plantilla"


def test_tipo_mismo_enlace_repetido():
    url = "https://medio.example/noticia-compartida"
    evs = [_ev(1000, "a.bsky.social", url, "noticia uno"),
           _ev(1001, "b.bsky.social", url, "noticia uno"),
           _ev(1002, "c.bsky.social", url, "noticia uno")]
    r = rasgos(evs)
    tipo, flags, _ = tipo_de(r)
    assert r["same_url_max"] == 3
    assert "mismo_enlace_repetido" in flags
