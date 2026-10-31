#!/usr/bin/env python3
"""Agrupa publicaciones en acontecimientos candidatos. No confirma hechos.
Solo crea/actualiza eventos automáticos; no toca items, fichas ni eventos manuales.
"""
import argparse,hashlib,os,re,sqlite3,sys,unicodedata
from datetime import datetime,timezone,timedelta
from pathlib import Path
DB=Path(os.environ.get('OBS_DB',Path(__file__).resolve().parent/'data'/'observatorio.db'))
TOPIC=os.environ.get('OBS_EVENT_TOPIC','frontera_sur')
WINDOW=int(os.environ.get('OBS_EVENT_WINDOW_DAYS','30'))
LOOKBACK=int(os.environ.get('OBS_EVENT_LOOKBACK_DAYS','45'))
STOP={'para','sobre','entre','desde','hasta','tras','ante','este','esta','estos','estas','como','donde','cuando','porque','segun','contra','despues','antes','nuevo','nueva','ultima','ultimo','hoy','ayer','directo','ultima','hora','noticias','video','fotos','asi','mas','menos','sera','puede','hace','sido','sido'}
def clean(s): return ' '.join(re.sub(r'<[^>]+>',' ',str(s or '')).split())
def toks(s):
 s=unicodedata.normalize('NFKD',clean(s)).encode('ascii','ignore').decode().lower()
 s=re.sub(r'\s+-\s+[^-]{2,80}$','',s)
 return {w for w in re.findall(r'[a-z0-9]{4,}',s) if w not in STOP}
def jac(a,b):
 u=a|b
 return len(a&b)/len(u) if u else 0
def db():
 c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); return c
def init(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,topic TEXT NOT NULL,title TEXT NOT NULL,summary TEXT,status TEXT NOT NULL DEFAULT 'publicado_sin_confirmar',first_published TEXT,last_published TEXT,n_publications INTEGER DEFAULT 0,n_sources INTEGER DEFAULT 0,source_kind TEXT NOT NULL DEFAULT 'auto',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS event_items(event_id TEXT NOT NULL,item_id TEXT NOT NULL,PRIMARY KEY(event_id,item_id));
 CREATE TABLE IF NOT EXISTS event_aliases(item_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,linked_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS event_responses(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL,actor TEXT,response TEXT,url TEXT,published TEXT,created_at TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_events_topic_date ON events(topic,first_published DESC);
 CREATE INDEX IF NOT EXISTS idx_event_items_item ON event_items(item_id);
 ''')
 for col,typ in [('review_status',"TEXT NOT NULL DEFAULT 'auto'"),('needs_review','INTEGER NOT NULL DEFAULT 0'),('review_reason','TEXT'),('reviewed_at','TEXT'),('signature','TEXT')]:
  try: c.execute(f'ALTER TABLE events ADD COLUMN {col} {typ}')
  except sqlite3.OperationalError: pass
def run(apply):
 if not DB.exists(): print('no db',DB,file=sys.stderr); return 2
 c=db(); init(c)
 since=(datetime.now(timezone.utc)-timedelta(days=LOOKBACK)).isoformat()
 rows=c.execute("SELECT id,title,url,source,published FROM items WHERE topic=? AND published>=? AND id NOT IN (SELECT ei.item_id FROM event_items ei JOIN events e ON e.id=ei.event_id WHERE e.source_kind='manual') ORDER BY published",(TOPIC,since)).fetchall()
 groups=[]
 for r in rows:
  t=toks(r['title'])
  if not t: continue
  placed=False
  for g in groups:
   if abs((datetime.fromisoformat(r['published'])-datetime.fromisoformat(g['last']))).days>WINDOW: continue
   if len(t&g['tokens'])>=2 and jac(t,g['tokens'])>=0.35:
    g['items'].append(r); g['tokens']|=t; g['last']=r['published']; placed=True; break
  if not placed: groups.append({'tokens':set(t),'items':[r],'last':r['published']})
 candidates=[g for g in groups if len(g['items'])>=2]
 print(f'topic={TOPIC} items={len(rows)} candidates={len(candidates)}')
 if not apply:
  for g in candidates[:10]: print(len(g['items']),g['items'][0]['title'][:110])
  return 0
 now=datetime.now(timezone.utc).isoformat(timespec='seconds')
 try:
  # Alias persistentes: cualquier item ya visto recuerda su evento.
  c.execute("INSERT OR IGNORE INTO event_aliases(item_id,event_id,linked_at) SELECT ei.item_id,ei.event_id,? FROM event_items ei JOIN events e ON e.id=ei.event_id WHERE e.source_kind='auto'",(now,))
  old={r['id']:r for r in c.execute("SELECT * FROM events WHERE topic=? AND source_kind='auto'",(TOPIC,)).fetchall()}
  c.execute("DELETE FROM event_items WHERE event_id IN (SELECT id FROM events WHERE topic=? AND source_kind='auto')",(TOPIC,))
  used=set()
  for g in candidates:
   ids=sorted(x['id'] for x in g['items'])
   found=c.execute("SELECT event_id,COUNT(*) n FROM event_aliases WHERE item_id IN (%s) GROUP BY event_id ORDER BY n DESC" % ','.join('?'*len(ids)),ids).fetchall()
   eid=None
   for r in found:
    if r['event_id'] in old and r['event_id'] not in used: eid=r['event_id']; break
   if eid is None: eid=hashlib.sha256((TOPIC+'|'+'|'.join(ids)).encode()).hexdigest()[:16]
   used.add(eid)
   its=sorted(g['items'],key=lambda x:x['published']); title=min((x['title'] for x in its),key=len)
   src=len({x['source'] for x in its if x['source']})
   summary=f'{len(its)} publicaciones de {src} fuentes entre {its[0]["published"][:10]} y {its[-1]["published"][:10]}.'
   ts=[toks(x['title']) for x in its]; pairs=[jac(ts[i],ts[j]) for i in range(len(ts)) for j in range(i+1,len(ts))]; coh=sum(pairs)/len(pairs) if pairs else 0
   reasons=[]
   if src<=1: reasons.append('una sola fuente')
   if coh<0.30: reasons.append('cohesión baja')
   needs=1 if reasons else 0; reason=', '.join(reasons) if reasons else None
   prev=old.get(eid)
   review_status=prev['review_status'] if prev else 'auto'
   reviewed_at=prev['reviewed_at'] if prev else None
   if review_status in ('approved','hidden'):
    needs=0; reason=None
   signature=min(ids)
   if prev:
    c.execute("UPDATE events SET title=?,summary=?,first_published=?,last_published=?,n_publications=?,n_sources=?,signature=?,review_status=?,needs_review=?,review_reason=?,reviewed_at=?,updated_at=? WHERE id=?",(title,summary,its[0]['published'],its[-1]['published'],len(its),src,signature,review_status,needs,reason,reviewed_at,now,eid))
   else:
    c.execute('INSERT INTO events(id,topic,title,summary,status,review_status,needs_review,review_reason,signature,reviewed_at,first_published,last_published,n_publications,n_sources,source_kind,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,TOPIC,title,summary,'publicado_sin_confirmar',review_status,needs,reason,signature,reviewed_at,its[0]['published'],its[-1]['published'],len(its),src,'auto',now,now))
   c.executemany('INSERT OR IGNORE INTO event_items(event_id,item_id) VALUES(?,?)',[(eid,x['id']) for x in its])
   c.executemany('INSERT OR REPLACE INTO event_aliases(item_id,event_id,linked_at) VALUES(?,?,?)',[(x['id'],eid,now) for x in its])
  if used:
   q=','.join('?'*len(used)); c.execute("DELETE FROM events WHERE topic=? AND source_kind='auto' AND id NOT IN (%s)" % q,(TOPIC,*used))
  else:
   c.execute("DELETE FROM events WHERE topic=? AND source_kind='auto'",(TOPIC,))
  c.commit(); print('written',len(candidates))
 except Exception as e:
  c.rollback(); print('error',e,file=sys.stderr); return 1
 finally: c.close()
 return 0
if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true'); a=ap.parse_args(); raise SystemExit(run(a.apply))
