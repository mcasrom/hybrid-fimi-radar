#!/usr/bin/env python3
"""Mueve titulares antiguos a items_history. Dry-run por defecto."""
import argparse,sqlite3,os,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
DB=Path(os.environ.get('OBS_DB',Path(__file__).resolve().parent/'data'/'observatorio.db'))
DAYS=int(os.environ.get('OBS_RETENTION_DAYS','90'))
def conn():
 c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); return c
def init(c):
 c.executescript('''CREATE TABLE IF NOT EXISTS items_history(id TEXT PRIMARY KEY,topic TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,source TEXT,published TEXT,query TEXT,fetched TEXT NOT NULL,archived_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_hist_topic_date ON items_history(topic,published DESC);''')
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true'); a=ap.parse_args()
 if not DB.exists(): print('no db',DB,file=sys.stderr); return 2
 c=conn(); init(c); cutoff=(datetime.now(timezone.utc)-timedelta(days=DAYS)).isoformat(timespec='seconds')
 n=c.execute('SELECT COUNT(*) FROM items WHERE published < ?',(cutoff,)).fetchone()[0]
 print(f'db={DB} cutoff={cutoff} older={n} apply={a.apply}')
 if not a.apply or n==0: return 0
 try:
  c.execute('BEGIN IMMEDIATE')
  c.execute('INSERT OR REPLACE INTO items_history(id,topic,title,url,source,published,query,fetched,archived_at) SELECT id,topic,title,url,source,published,query,fetched,? FROM items WHERE published < ?',(datetime.now(timezone.utc).isoformat(timespec='seconds'),cutoff))
  c.execute('DELETE FROM items WHERE published < ?',(cutoff,))
  c.commit(); print('archived',n)
 except Exception as e:
  c.rollback(); print('error',e,file=sys.stderr); return 1
 finally: c.close()
 return 0
if __name__=='__main__': raise SystemExit(main())
