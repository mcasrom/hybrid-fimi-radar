#!/usr/bin/env python3
"""Medios establecidos + fraccion de dominios mainstream (heuristica).

Sirve para el chip "eco de prensa" (dashboard) y para el cap `mainstream_cap`
(scoring): si la mayoria de los dominios amplificados por un cluster son de
medios consolidados, la coordinacion observada es compatible con cobertura
periodistica normal, no con una campana inautentica.

NO es una verdad absoluta: es una lista curada y ampliable.
"""
import urllib.parse

MAINSTREAM = set("""
eldiario.es elpais.com publico.es elmundo.es abc.es lavanguardia.com
elconfidencial.com infolibre.es rtve.es cadenaser.com 20minutos.es
europapress.es elperiodico.com larazon.es theobjective.com vozpopuli.com
elespanol.com ctxt.es elplural.com infobae.com elcomercio.pe efe.com
huffingtonpost.es elboletin.com elfarodeceuta.es elsaltodiario.com
elordenmundial.com eldebate.com elindependiente.com economiadigital.es
bbc.com bbc.co.uk reuters.com apnews.com theguardian.com cnn.com nbcnews.com
nytimes.com washingtonpost.com motherjones.com time.com aljazeera.com
lemonde.fr france24.com bfmtv.com cnews.fr 20minutes.fr franceinfo.fr
euronews.com dw.com zeit.de spiegel.de tagesspiegel.de stern.de taz.de rnd.de
sverigesradio.se dn.se svt.se aftonbladet.se expressen.se etc.se tagesschau.de
npr.org politico.eu thehill.com news.sky.com cnbc.com forbes.com bloomberg.com
ft.com wsj.com usatoday.com latimes.com independent.co.uk thetimes.co.uk
telegraph.co.uk courrierinternational.com information.tv5monde.com
allsides.com elcorreo.com diariovasco.com heraldo.es lne.es farodevigo.es
lavozdegalicia.es canarias7.es laprovincia.es diariodeibiza.es
""".split())


def _host(url):
    u = (url or "").strip()
    if not u:
        return ""
    h = urllib.parse.urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def mainstream_frac(urls):
    """Fraccion de URLs cuyo dominio esta en MAINSTREAM (0.0 si no hay URLs)."""
    tot = ms = 0
    for u in urls or []:
        h = _host(u)
        if not h:
            continue
        tot += 1
        if h in MAINSTREAM:
            ms += 1
    return (ms / tot) if tot else 0.0
