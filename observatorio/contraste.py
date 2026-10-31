#!/usr/bin/env python3
"""Contraste con verificadores. Enlaza verificaciones publicadas a eventos candidatos.
No declara bulos ni veredictos: solo coincidencia de titulares.
"""
import argparse,hashlib,os,re,sqlite3,sys,time,urllib.request,unicodedata,xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
DB=Path(os.environ.get('OBS_DB',Path(__file__).resolve().parent/'data'/'observatorio.db'))
FEEDS=[('Maldita','https://maldita.es/feed'),('Newtral','https://www.newtral.es/feed/')]
UA='Mozilla/5.0 (compatible; ObservatorioPublicado/1.0)'
RET=60
STOP={'para','sobre','entre','desde','hasta','tras','ante','este','esta','estos','estas','como','donde','cuando','porque','segun','contra','despues','antes','nuevo','nueva','ultima','ultimo','hoy','ayer','directo','hora','noticias','video','fotos','asi','mas','menos','sera','puede','hace','sido','gobierno','espana','marruecos','ceuta','melilla','tras','solo','desde'}
def clean(s): return ' '.join(re.sub(r'<[^>]+>',' ',str(s or '')).split())
def toks(s):
 s=unicodedata.normalize('NFKD',clean(s)).encode('ascii','ignore').decode().lower()
 return {w for w in re.findall(r'[a-z0-9]{4,}',s) if w not in STOP}
def pub(s):
 try:
  d=parsedate_to_datetime(s); return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
 except Exception: return None
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':UA})
 with urllib.request.urlopen(req,timeout=15) as r: return r.read()
def db():
 c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); return c
def init(c):
 c.executescript('''CREATE TABLE IF NOT EXISTS factchecks(url TEXT PRIMARY KEY,source TEXT NOT NULL,title TEXT NOT NULL,published TEXT,fetched TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS event_factchecks(event_id TEXT NOT NULL,factcheck_url TEXT NOT NULL,overlap TEXT,created_at TEXT NOT NULL,PRIMARY KEY(event_id,factcheck_url));
 CREATE INDEX IF NOT EXISTS idx_fc_pub ON factchecks(published DESC);''')
def run(apply):
 if not DB.exists(): print('no db',DB,file=sys.stderr); return 2
 c=db(); init(c); now=datetime.now(timezone.utc); added=0; errors=[]
 for name,url in FEEDS:
  try: raw=get(url)
  except Exception as e: errors.append(f'{name}: {str(e)[:100]}'); continue
  try: root=ET.fromstring(raw)
  except Exception as e: errors.append(f'{name}:xml: {str(e)[:80]}'); continue
  for it in root.findall('./channel/item'):
   title=clean(it.findtext('title')); link=(it.findtext('link') or '').strip(); p=pub(it.findtext('pubDate'))
   if not title or not link or not p or p<now-timedelta(days=RET): continue
   try:
    cur=c.execute('INSERT OR IGNORE INTO factchecks(url,source,title,published,fetched) VALUES(?,?,?,?,?)',(link,name,title,p.isoformat(),now.isoformat(timespec='seconds'))); added+=cur.rowcount
   except sqlite3.Error as e: errors.append(f'{name}:db:{e}')
 c.commit()
 if not apply:
  print('dry',added,'factchecks'); c.close(); return 0
 # link factchecks to events by >=2 significant overlapping tokens
 try:
  fcs=[dict(r) for r in c.execute('SELECT url,source,title,published FROM factchecks WHERE published>=?',((now-timedelta(days=RET)).isoformat(),)).fetchall()]
  evs=c.execute('SELECT id,title,first_published,last_published FROM events WHERE topic="frontera_sur"').fetchall()
  c.execute('DELETE FROM event_factchecks')
  links=0
  for e in evs:
   ititles=[r['title'] for r in c.execute('SELECT i.title FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=?',(e['id'],))]
   et=toks(e['title']); [et.update(toks(t)) for t in ititles]
   for fc in fcs:
    ft=toks(fc['title']); shared=et&ft
    if len(shared)<3 or not any(len(x)>=6 for x in shared): continue
    try:
     fd=datetime.fromisoformat(fc['published']); a=datetime.fromisoformat(e['first_published']); b=datetime.fromisoformat(e['last_published'])
     if fd < a-timedelta(days=45) or fd > b+timedelta(days=45): continue
    except Exception: pass
    c.execute('INSERT OR IGNORE INTO event_factchecks(event_id,factcheck_url,overlap,created_at) VALUES(?,?,?,?)',(e['id'],fc['url'],','.join(sorted(shared))[:200],now.isoformat(timespec='seconds'))); links+=1
  c.commit(); print('factchecks',len(fcs),'links',links,'added',added)
 except Exception as e:
  c.rollback(); print('link error',e,file=sys.stderr); return 1
 finally: c.close()
 return 0
if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true'); a=ap.parse_args(); raise SystemExit(run(a.apply))
