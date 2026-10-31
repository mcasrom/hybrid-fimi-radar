#!/usr/bin/env python3
"""Captura automática de titulares para el Observatorio de lo publicado.
Fuentes: Google News RSS + feeds directos (ES/MA/DZ/FR/UK). Solo titulares y enlaces.
"""
import hashlib,json,os,re,sqlite3,sys,time,urllib.request,xml.etree.ElementTree as ET
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
 'protestas_juveniles':{'label':'Protestas juveniles','queries':['protestas juveniles España','disturbios jóvenes España','movilización estudiantil España'],'terms':['protesta','protestas','protestation','manifestation','manifestacion','manifestación','manifestante','manifestantes','joven','jovenes','jeune','jeunes','jeunesse','juvenil','juveniles','estudiant','estudiante','estudiantes','étudiant','disturbio','disturbios','emeute','émeute','riot','riots','blocus','movilizacion','movilizaciones','proteste','protesten','protestaufruf','protestaufrufe','jugend','jugendprotest','jugendprostesten','schulerprotest','schülerprotest','studenten','studentenbewegung']},
 'elecciones_generales':{'label':'Elecciones generales','queries':['elecciones generales España 29N','campaña electoral España 2026','elecciones 29 noviembre España'],'terms':['eleccion','elección','elecciones','election','elections','reelection','reeleccion','élection','electoral','campaña','precampaña','precampana','campagne','29n','voto','vote','candidat','candidate','urnas','wahl','wahlen','wahlkampf','kandidat','kandidaten','abstimmung','stimme','elezioni','elezione','campagna','candidato','candidati','scrutin','выборы','кампания','выборах','انتخابات','الحملة']},
 'infraestructuras_espana':{'label':'Infraestructuras España','queries':['infraestructuras España Ministerio Transportes','alta velocidad incidencia España','autovías España conservación','ADIF Renfe incidencias tren'],'terms':['infraestructura','infraestructuras','transportes','transporte','adif','renfe','autovia','autovías','alta velocidad','tren','trenes','cercanias','cercanías','accidente','accidentes','incidencia','incidencias','obra','obras','carretera','carreteras','aeropuerto','aeropuertos','puerto','puertos','conservacion','conservación','mitms']},
}
def now(): return datetime.now(timezone.utc)
def clean(x): return ' '.join(re.sub(r'<[^>]+>',' ',str(x or '')).split())
def norm(s): return re.sub(r'[^\w]+',' ',s.lower()).strip()
STATE_NAMES=('rt','tass','ria novosti','sputnik','cgtn','global times','xinhua','press tv','hispan','trt','anadolu','telesur','cubadebate','granma','irna','tasnim','alalam')
def source_class(source,source_type):
 if source_type=='official': return 'official'
 return 'state' if any(x in (source or '').lower() for x in STATE_NAMES) else 'media'
def has_term(t,term):
 term=term.lower()
 if any(ord(ch)>127 for ch in term): return term in t
 return re.search(r'(?<!\w)'+re.escape(term)+r'\w{0,4}(?!\w)',t) is not None
FRONTERA_GEO=['ceuta','melilla','marruecos','morocco','maroc','marocain','marocaine','المغرب','سبتة','مليلية','сеута','мелилья','марокко']
FRONTERA_CONTEXT=['frontera','frontière','frontiere','fronteriza','migracion','migration','migratoire','migrante','inmigrante','patera','salto','valla','naval','navire','militar','militaire','militaires','dron','armada','guardia civil','estrecho','détroit','detroit','gibraltar','repatri','empadronamiento','menores','diplomatic','rey','reyes','felipe','visita','gobierno','asalto','cni','actitud','pasiva','contener','amenaza','homenaje','milicia','milicias','rifeño','rifeños','passage','passages','immigration','delegacion','policia','interior','crisis migratoria','mena','sahara','pêche','peche','الهجرة','المغرب','سبتة','مليلية','миграция','сеута','марокко']
INFRA_EXCLUDE=['futbol','fútbol','liga','entrenador','club','deportivo','baloncesto','judo','partido','cantera','fichaje','voleibol','atletismo']
INFRA_CONTEXT=['espana','españa','espanol','espanola','espanoles','espanolas','spain','adif','renfe','mitms','dgt','ministerio','madrid','barcelona','valencia','sevilla','bilbao','malaga','zaragoza','alta velocidad','tren','trenes','catenaria','ferroviario','urda','puente','congreso','cortes','junta','diputacion','colau','montero']
FRONTERA_EXCLUDE=['futbol','fútbol','baloncesto','balonmano','judo','liga','club','deportivo','campeonato','deporte','atletismo','voleibol','u.d.','ud melilla','bm ','bm.','atletico','atlético','filial','preparacion','preparación','u d','c.f.']
SPAIN_CONTEXT=['espana','españa','spain','spanish','espagne','spanien','spagna','espanha','испания','إسبانيا','اسبانيا','29n','29 de noviembre','elecciones generales','campana electoral','campaña electoral','mesas electorales','junta electoral','congreso','senado','moncloa','pedro sanchez','sanchez','feijoo','feijóo','psoe','vox','sumar','podemos','elecciones 2026','sorteo','supremo','tribunal constitucional','audiencia nacional']
def relevant(topic,title):
 t=norm(title)
 if topic=='elecciones_generales':
  return any(has_term(t,c) for c in SPAIN_CONTEXT) and any(has_term(t,term) for term in TOPICS[topic]['terms'])
 if topic=='protestas_juveniles' and any(x in t for x in ['patriot','ukrainekrieg','ukraine-krieg','ucrania','misiles','missiles']): return False
 if topic=='frontera_sur':
  if any(x in t for x in FRONTERA_EXCLUDE): return False
  return any(has_term(t,x) for x in FRONTERA_GEO) and any(has_term(t,x) for x in FRONTERA_CONTEXT)
 if topic=='infraestructuras_espana':
  if any(x in t for x in INFRA_EXCLUDE): return False
  strong=['adif','renfe','mitms','dgt','alta velocidad','autovia','autovía','cercanias','cercanías','accidente','carretera','catenaria','ferroviario','urda','infraestructura','infraestructuras','transporte','movilidad']
  if any(has_term(t,x) for x in strong): return True
  return any(has_term(t,x) for x in INFRA_CONTEXT) and any(has_term(t,term) for term in TOPICS[topic]['terms'])
 return any(has_term(t,term) for term in TOPICS[topic]['terms'])
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
    for col,typ in [('source_type',"TEXT NOT NULL DEFAULT 'media'"),('source_lang',"TEXT NOT NULL DEFAULT 'es'"),('source_class',"TEXT NOT NULL DEFAULT 'media'")]:
        try: c.execute(f'ALTER TABLE items ADD COLUMN {col} {typ}')
        except sqlite3.OperationalError: pass
    # backfill de idioma para fuentes directas ya existentes
    for f in feeds:
        try:
            c.execute('UPDATE items SET source_lang=? WHERE source=?',(f.get('idioma') or 'es',f['name']))
            c.execute('UPDATE items SET source_class=? WHERE source=?',(source_class(f['name'],'official' if f.get('tipo')=='official' else 'media'),f['name']))
        except sqlite3.Error: pass
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
                    cur=c.execute('INSERT OR IGNORE INTO items(id,topic,title,url,source,published,query,fetched,source_type,source_lang,source_class) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,tpc,title,link,source,pub.isoformat(),('google:'+name) if kind=='google' else 'direct:'+name,now().isoformat(timespec='seconds'),('official' if (kind=='direct' and fm.get(name,{}).get('tipo')=='official') else 'media'),('es' if kind=='google' else (fm.get(name,{}).get('idioma') or 'es')),source_class(source,('official' if (kind=='direct' and fm.get(name,{}).get('tipo')=='official') else 'media'))))
                    added+=cur.rowcount
                    if kind=='direct' and name in health: health[name]['items']+=1
                except sqlite3.Error as e: errors.append(f'{name}:db: {e}')
    c.commit()
    stamp=now().isoformat(timespec='seconds')
    latest={'updated_at':stamp,'source':'Google News RSS + feeds directos','note':'Titulares capturados automáticamente; no son hechos verificados.','topics':{}}
    for topic,meta in TOPICS.items():
        es=c.execute("SELECT id,title,url,source,source_type,source_lang,source_class,published FROM items WHERE topic=? AND source_lang='es' ORDER BY published DESC LIMIT 20",(topic,)).fetchall()
        intl_all=c.execute("SELECT id,title,url,source,source_type,source_lang,source_class,published FROM items WHERE topic=? AND source_lang!='es' ORDER BY published DESC LIMIT 100",(topic,)).fetchall()
        bylang={}
        for r in intl_all: bylang.setdefault(r['source_lang'] or '?',[]).append(r)
        intl=[]; seen_intl=set()
        for lang in sorted(bylang):
            for r in bylang[lang][:2]: intl.append(r); seen_intl.add(r['id'])
        for r in intl_all:
            if len(intl)>=20: break
            if r['id'] not in seen_intl: intl.append(r); seen_intl.add(r['id'])
        rows=list(es)+intl
        if len(rows)<40:
            seen={r['id'] for r in rows}
            extra=c.execute('SELECT id,title,url,source,source_type,source_lang,source_class,published FROM items WHERE topic=? ORDER BY published DESC LIMIT 100',(topic,)).fetchall()
            rows += [r for r in extra if r['id'] not in seen][:40-len(rows)]
        rows=sorted(rows,key=lambda r:r['published'],reverse=True)[:40]
        trend=[dict(r) for r in c.execute('SELECT substr(published,1,10) d,COUNT(*) n FROM items WHERE topic=? AND published>=? GROUP BY substr(published,1,10) ORDER BY d',(topic,(now()-timedelta(days=14)).isoformat())).fetchall()]
        latest['topics'][topic]={'label':meta['label'],'count':len(rows),'sources':len({r['source'] for r in rows if r['source']}),'trend':trend,'items':[dict(r) for r in rows]}
    latest['feed_errors']=errors[:15]
    fh={'updated_at':stamp,'total':len(health),'ok':sum(1 for x in health.values() if x['status']=='ok'),'error':sum(1 for x in health.values() if x['status']=='error'),'pending':sum(1 for x in health.values() if x['status']=='pending'),'feeds':sorted(health.values(),key=lambda x:x['name'])}
    status_topics={}
    for topic,meta in TOPICS.items():
        row=c.execute('''SELECT COUNT(*) n, COUNT(DISTINCT source) sources,
            SUM(CASE WHEN source_type='official' THEN 1 ELSE 0 END) official,
            SUM(CASE WHEN source_class='state' THEN 1 ELSE 0 END) state,
            MAX(published) last_published
            FROM items WHERE topic=? AND published>=?''',(topic,cutoff.isoformat())).fetchone()
        langs={r['lang']:r['n'] for r in c.execute("SELECT COALESCE(source_lang,'?') lang,COUNT(*) n FROM items WHERE topic=? AND published>=? GROUP BY COALESCE(source_lang,'?') ORDER BY n DESC",(topic,cutoff.isoformat())).fetchall()}
        tops=[{'source':r['source'],'n':r['n']} for r in c.execute("SELECT source,COUNT(*) n FROM items WHERE topic=? AND published>=? AND source<>'' GROUP BY source ORDER BY n DESC LIMIT 5",(topic,cutoff.isoformat())).fetchall()]
        n=row['n'] or 0
        status_topics[topic]={'label':meta['label'],'count_45d':n,'sources':row['sources'] or 0,
            'official':row['official'] or 0,'state':row['state'] or 0,
            'official_pct':round((row['official'] or 0)*100/n,1) if n else 0,
            'state_pct':round((row['state'] or 0)*100/n,1) if n else 0,
            'languages':langs,'top_sources':tops,'last_published':row['last_published']}
    status={'updated_at':stamp,'window_days':DAYS,'topics':status_topics,
        'feeds':{'total':fh['total'],'ok':fh['ok'],'error':fh['error'],'pending':fh['pending'],'errors':errors[:10]}}
    latest['status']=status
    OUT.parent.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(latest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(OUT)
    sp=OUT.parent/'status.json'; tmp=sp.with_suffix('.tmp'); tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(sp)
    hp=Path(os.environ.get('OBS_HEALTH',OUT.parent/'feed_health.json')); hp.write_text(json.dumps(fh,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    ok=fh['ok']>0
    print(json.dumps({'ok':ok,'feeds':len(feeds),'feed_health':{'ok':fh['ok'],'error':fh['error'],'pending':fh['pending']},'added':added,'topics':{k:v['count'] for k,v in latest['topics'].items()},'errors':errors[:8]},ensure_ascii=False))
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(run())
