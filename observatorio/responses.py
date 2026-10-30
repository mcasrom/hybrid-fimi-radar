#!/usr/bin/env python3
"""Genera respuestas oficiales candidatas desde publicaciones oficiales de cada evento.
No confirma que sean la respuesta del actor ni que el evento esté confirmado.
"""
import argparse,os,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
DB=Path(os.environ.get('OBS_DB',Path(__file__).resolve().parent/'data'/'observatorio.db'))
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def db():
 c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); return c
def main(apply):
 if not DB.exists(): print('no db',DB,file=sys.stderr); return 2
 c=db()
 for col,typ in [('kind',"TEXT DEFAULT 'publication_official'"),('status',"TEXT DEFAULT 'candidato'"),('created_by',"TEXT DEFAULT 'auto'")]:
  try: c.execute(f'ALTER TABLE event_responses ADD COLUMN {col} {typ}')
  except sqlite3.OperationalError: pass
 c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_resp_event_url ON event_responses(event_id,url)')
 rows=c.execute("""SELECT e.id,e.topic,i.id item_id,i.title,i.url,i.source,i.published
  FROM events e JOIN event_items ei ON ei.event_id=e.id JOIN items i ON i.id=ei.item_id
  WHERE i.source_type='official' AND e.topic='frontera_sur'""").fetchall()
 print('official_publications',len(rows),'apply',apply)
 if not apply: c.close(); return 0
 try:
  c.execute("DELETE FROM event_responses WHERE created_by='auto'")
  for r in rows:
   c.execute('INSERT OR IGNORE INTO event_responses(event_id,actor,response,url,published,created_at,kind,status,created_by) VALUES(?,?,?,?,?,?,?,?,?)',(r['id'],r['source'],r['title'],r['url'],r['published'],now(),'publication_official','candidato','auto'))
  c.commit(); print('written',len(rows))
 except Exception as e:
  c.rollback(); print('error',e,file=sys.stderr); return 1
 finally: c.close()
 return 0
if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true'); a=ap.parse_args(); raise SystemExit(main(a.apply))
