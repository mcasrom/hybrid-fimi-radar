#!/usr/bin/env python3
"""Elimina items que ya no cumplen la relevancia temática. Dry-run por defecto."""
import argparse,sqlite3,sys,os
from pathlib import Path
from ingest import relevant
DB=Path(os.environ.get('OBS_DB',Path(__file__).resolve().parent/'data'/'observatorio.db'))
def main(apply,args_topic=None):
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA busy_timeout=30000')
 topic=args_topic or 'frontera_sur'
 rows=c.execute('SELECT id,topic,title FROM items WHERE topic=?',(topic,)).fetchall()
 bad=[r for r in rows if not relevant(r['topic'],r['title'])]
 print('topic',topic,'reviewed',len(rows),'bad',len(bad),'apply',apply)
 for r in bad[:15]: print(r['id'],r['title'][:120])
 if apply and bad:
  c.executemany('DELETE FROM items WHERE id=?',[(r['id'],) for r in bad]); c.commit(); print('deleted',len(bad))
 c.close(); return 0
if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true'); ap.add_argument('--topic',default='frontera_sur'); a=ap.parse_args(); raise SystemExit(main(a.apply,a.topic))
