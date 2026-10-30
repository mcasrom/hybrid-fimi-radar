#!/usr/bin/env python3
"""Captura automática de titulares para el Observatorio de lo publicado.
Fuentes: Google News RSS + feeds directos (ES/MA/DZ/FR/UK). Solo titulares y enlaces.
"""
import hashlib,json,os,re,sqlite3,sys,urllib.request,xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('OBS_DB',ROOT/'data'/'observatorio.db'))
OUT=Path(os.environ.get('OBS_LATEST',ROOT/'data'/'latest.json'))
UA='Mozilla/5.0 (compatible; ObservatorioPublicado/1.0; +https://fimi.viajeinteligencia.com/observatorio/)'
DAYS=45
TOPICS={
 'frontera_sur':{'label':'Frontera Sur','queries':['Ceuta Marruecos','Melilla Marruecos','frontera sur España Marruecos'],'terms':['ceuta','melilla','marruecos','maroc','morocco','frontera','frontière','frontiere','migracion','migración','migration','migratoire','gibraltar','سبتة','مليلية','المغرب']},
 'protestas_juveniles':{'label':'Protestas juveniles','queries':['protestas juveniles España','disturbios jóvenes España','movilización estudiantil España'],'terms':['protesta','protestation','manifestation','joven','jeune','jeunesse','juvenil','estudiant','étudiant','disturbio','emeute','émeute','riot','blocus','moviliz']},
 'elecciones_generales':{'label':'Elecciones generales','queries':['elecciones generales España 29N','campaña electoral España 2026','elecciones 29 noviembre España'],'terms':['eleccion','elección','election','élection','electoral','campaña','campagne','29n','voto','vote','candidat','candidate','espana','españa','spain','espagne']},
 'infraestructuras_espana':{'label':'Infraestructuras España','queries':['infraestructuras España Ministerio Transportes','alta velocidad incidencia España','autovías España conservación','ADIF Renfe incidencias tren'],'terms':['infraestructura','transportes','transporte','adif','renfe','autovia','autovía','alta velocidad','tren','cercanias','cercanías','accidente','incidencia','obra','carretera','aeropuerto','puerto','conservacion','conservación','mitms']},
}
def now(): return datetime.now(timezone.utc)
def clean(x): return ' '.join(re.sub(r'<[^>]+>',' ',str(x or '')).split())
def norm(s): return re.sub(r'[^a-z0-9áéíóúüñçàèìòùâêîôûëïü ]',' ',s.lower()).strip()
def relevant(topic,title):
 t=norm(title); return any(term.lower() in t for term in TOPICS[topic]['terms'])
def parse_date(s):
 try:
  d=parsedate_to_datetime(s); return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
 except Exception: return None
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':UA})
 for attempt in range(2):
  try:
   with urllib.request.urlopen(req,timeout=12) as r: return r.read()
  except Exception:
   if attempt==1: raise
   time.sleep(1)
def db():
 DB.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL')
 c.executescript('''CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,topic TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,source TEXT,published TEXT,query TEXT,fetched TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_items_topic_date ON items(topic,published DESC); CREATE INDEX IF NOT EXISTS idx_items_url ON items(url);''')
 return c
def load_feeds():
 try: return json.loads((ROOT/'feeds.json').read_text(encoding='utf-8'))
 except Exception as e: print('feeds.json:',e,file=sys.stderr); return []
def gurl(q): return 'https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q,'hl':'es','gl':'ES','ceid':'ES:es'})
def run():
    c=db(); added=0; errors=[]; cutoff=now()-timedelta(days=DAYS); feeds=load_feeds(); fm={f['name']:f for f in feeds}
    health={f['name']:{'name':f['name'],'url':f['url'],'topics':f.get('topics',[]),'status':'pending','items':0,'error':None,'last_attempt':None} for f in feeds}
    jobs=[]
    for topic,meta in TOPICS.items():
        for q in meta['queries']: jobs.append(('google',topic,q,gurl(q)))
    for f in feeds: jobs.append(('direct','__all__',f['name'],f['url']))
    raw={}
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut={ex.submit(get,j[3]):j for j in jobs}
        for f in as_completed(fut):
            j=fut[f]
            try: raw[(j[0],j[1],j[2],j[3])]=f.result()
            except Exception as e:
                msg=str(e)[:160]
                if j[0]=='direct' and j[2] in health:
                    health[j[2]]['status']='error'; health[j[2]]['error']=msg; health[j[2]]['last_attempt']=now().isoformat(timespec='seconds')
                errors.append(f'{j[0]}:{j[2]}: {msg}')
    for (kind,topic,name,url),body in raw.items():
        try: root=ET.fromstring(body)
        except Exception as e:
            msg=f'{name}:xml: {str(e)[:100]}'; errors.append(msg)
            if kind=='direct' and name in health:
                health[name]['status']='error'; health[name]['error']=msg; health[name]['last_attempt']=now().isoformat(timespec='seconds')
            continue
        feed_topics=fm.get(name,{}).get('topics',[]) if kind=='direct' else [topic]
        if kind=='direct' and name in health:
            health[name]['status']='ok'; health[name]['error']=None; health[name]['last_attempt']=now().isoformat(timespec='seconds')
        for it in root.findall('./channel/item'):
            title=clean(it.findtext('title')); link=(it.findtext('link') or '').strip()
            pub=parse_date(it.findtext('pubDate'))
            if not title or not link or not pub or pub<cutoff or pub>now()+timedelta(hours=6): continue
            for tpc in feed_topics:
                if not relevant(tpc,title): continue
                source=clean(it.findtext('source') or '') if kind=='google' else name
                iid=hashlib.sha256((tpc+'|'+link).encode()).hexdigest()[:24]
                try:
                    cur=c.execute('INSERT OR IGNORE INTO items(id,topic,title,url,source,published,query,fetched) VALUES(?,?,?,?,?,?,?,?)',(iid,tpc,title,link,source,pub.isoformat(),('google:'+name) if kind=='google' else 'direct:'+name,now().isoformat(timespec='seconds')))
                    added+=cur.rowcount
                    if kind=='direct' and name in health: health[name]['items']+=1
                except sqlite3.Error as e: errors.append(f'{name}:db: {e}')
    c.commit()
    stamp=now().isoformat(timespec='seconds')
    latest={'updated_at':stamp,'source':'Google News RSS + feeds directos','note':'Titulares capturados automáticamente; no son hechos verificados.','topics':{}}
    for topic,meta in TOPICS.items():
        rows=c.execute('SELECT id,title,url,source,published FROM items WHERE topic=? ORDER BY published DESC LIMIT 40',(topic,)).fetchall()
        trend=[dict(r) for r in c.execute('SELECT substr(published,1,10) d,COUNT(*) n FROM items WHERE topic=? AND published>=? GROUP BY substr(published,1,10) ORDER BY d',(topic,(now()-timedelta(days=14)).isoformat())).fetchall()]
        latest['topics'][topic]={'label':meta['label'],'count':len(rows),'sources':len({r['source'] for r in rows if r['source']}),'trend':trend,'items':[dict(r) for r in rows]}
    latest['feed_errors']=errors[:15]
    OUT.parent.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(latest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(OUT)
    fh={'updated_at':stamp,'total':len(health),'ok':sum(1 for x in health.values() if x['status']=='ok'),'error':sum(1 for x in health.values() if x['status']=='error'),'pending':sum(1 for x in health.values() if x['status']=='pending'),'feeds':sorted(health.values(),key=lambda x:x['name'])}
    hp=Path(os.environ.get('OBS_HEALTH',OUT.parent/'feed_health.json')); hp.write_text(json.dumps(fh,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    ok=fh['ok']>0
    print(json.dumps({'ok':ok,'feeds':len(feeds),'feed_health':{'ok':fh['ok'],'error':fh['error'],'pending':fh['pending']},'added':added,'topics':{k:v['count'] for k,v in latest['topics'].items()},'errors':errors[:8]},ensure_ascii=False))
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(run())
