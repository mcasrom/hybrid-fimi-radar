#!/usr/bin/env python3
"""Captura automática de publicaciones para el Observatorio de lo publicado.
Solo titulares y enlaces públicos. No verifica hechos ni atribuye intención.
"""
import hashlib, json, os, re, sqlite3, sys, time, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('OBS_DB',ROOT/'data'/'observatorio.db'))
OUT=Path(os.environ.get('OBS_LATEST',ROOT/'data'/'latest.json'))
UA='Mozilla/5.0 (compatible; ObservatorioPublicado/1.0; +https://fimi.viajeinteligencia.com/observatorio/)'
TOPICS={
 'frontera_sur':{'label':'Frontera Sur','queries':['Ceuta Marruecos','Melilla Marruecos','frontera sur España Marruecos'],'terms':['ceuta','melilla','marruecos','frontera']},
 'protestas_juveniles':{'label':'Protestas juveniles','queries':['protestas juveniles España','disturbios jóvenes España','movilización estudiantil España'],'terms':['protesta','joven','juvenil','estudiante','disturbio','movilizaci']},
 'elecciones_generales':{'label':'Elecciones generales','queries':['elecciones generales España 29N','campaña electoral España 2026','elecciones 29 noviembre España'],'terms':['eleccion','electoral','29n','campaña','voto','candidat']},
}
DAYS=45
def now(): return datetime.now(timezone.utc)
def clean(x): return ' '.join(re.sub(r'<[^>]+>',' ',str(x or '')).split())
def norm(s): return re.sub(r'[^a-z0-9áéíóúüñ ]',' ',s.lower()).strip()
def relevant(topic,title):
    t=norm(title); return any(term in t for term in TOPICS[topic]['terms'])
def parse_date(s):
    try:
        d=parsedate_to_datetime(s)
        return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: return None
def db():
    DB.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,topic TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,source TEXT,published TEXT,query TEXT,fetched TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_items_topic_date ON items(topic,published DESC); CREATE INDEX IF NOT EXISTS idx_items_url ON items(url);''')
    return c
def fetch(q):
    url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q,'hl':'es','gl':'ES','ceid':'ES:es'})
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=25) as r: return r.read()
def run():
    c=db(); added=0; errors=[]; cutoff=now()-timedelta(days=DAYS)
    for topic,meta in TOPICS.items():
        for q in meta['queries']:
            try: raw=fetch(q)
            except Exception as e: errors.append(f'{topic}:{q}: {e}'); continue
            try: root=ET.fromstring(raw)
            except Exception as e: errors.append(f'{topic}:xml: {e}'); continue
            for it in root.findall('./channel/item'):
                title=clean(it.findtext('title')); link=(it.findtext('link') or '').strip()
                pub=parse_date(it.findtext('pubDate')); source=clean(it.findtext('source') or '')
                if not title or not link or not pub or pub<cutoff or pub>now()+timedelta(hours=6): continue
                if not relevant(topic,title): continue
                iid=hashlib.sha256((topic+'|'+link).encode()).hexdigest()[:24]
                try:
                    cur=c.execute('INSERT OR IGNORE INTO items(id,topic,title,url,source,published,query,fetched) VALUES(?,?,?,?,?,?,?,?)',(iid,topic,title,link,source,pub.isoformat(),q,now().isoformat(timespec='seconds')))
                    added+=cur.rowcount
                except sqlite3.Error as e: errors.append(f'{topic}:db: {e}')
        c.commit()
    latest={'updated_at':now().isoformat(timespec='seconds'),'source':'Google News RSS','note':'Titulares capturados automáticamente; no son hechos verificados.','topics':{}}
    for topic,meta in TOPICS.items():
        rows=c.execute('SELECT id,title,url,source,published FROM items WHERE topic=? ORDER BY published DESC LIMIT 40',(topic,)).fetchall()
        latest['topics'][topic]={'label':meta['label'],'count':len(rows),'sources':len({r['source'] for r in rows if r['source']}),'items':[dict(r) for r in rows]}
    OUT.parent.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(latest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(OUT)
    print(json.dumps({'ok':not errors,'added':added,'topics':{k:v['count'] for k,v in latest['topics'].items()},'errors':errors[:10]},ensure_ascii=False))
    return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(run())
