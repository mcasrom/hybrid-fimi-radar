#!/usr/bin/env python3
"""Captura canales públicos de Telegram y cuentas públicas de Bluesky/Mastodon.
Solo publicaciones; no grafo, no clústeres, no atribución.
"""
import hashlib,html,json,os,re,sqlite3,sys,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
DB=Path(os.environ.get('OBS_DB',Path(__file__).resolve().parent/'data'/'observatorio.db'))
TOKEN_DB=Path(os.environ.get('OBS_SOCIAL_HEALTH',Path(__file__).resolve().parent/'data'/'social_health.json'))
UA='Mozilla/5.0 (compatible; ObservatorioPublicado/1.0)'
TOPICS={
 'frontera_sur':{'terms':['ceuta','melilla','marruecos','maroc','morocco','frontera','frontera sur','migracion','migración','migration','gibraltar']},
 'protestas_juveniles':{'terms':['protesta','protestacion','joven','juvenil','estudiante','disturbio','movilizacion','movilización','manifestacion','manifestación']},
 'elecciones_generales':{'terms':['eleccion','elección','electoral','campaña','campana','29n','voto','candidato','candidata','espana','españa']},
 'infraestructuras_espana':{'terms':['infraestructura','transportes','adif','renfe','autovia','autovía','alta velocidad','tren','cercanias','cercanías','accidente','carretera','aeropuerto','puerto']},
}
SOURCES=[
 {'id':'telegram:elfarodeceuta','kind':'telegram','name':'El Faro de Ceuta','handle':'elfarodeceuta','topics':['frontera_sur'],'official':False},
 {'id':'telegram:maldita_es','kind':'telegram','name':'Maldita','handle':'maldita_es','topics':['frontera_sur','protestas_juveniles','elecciones_generales'],'official':False},
 {'id':'telegram:sahelbrut','kind':'telegram','name':'Sahel Brut','handle':'sahelbrut','topics':['frontera_sur'],'official':False},
 {'id':'bluesky:elpais.com','kind':'bluesky','name':'El País','handle':'elpais.com','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':False},
 {'id':'bluesky:eldiario.es','kind':'bluesky','name':'elDiario.es','handle':'eldiario.es','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':False},
 {'id':'bluesky:europapress.es','kind':'bluesky','name':'Europa Press','handle':'europapress.es','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':False},
 {'id':'bluesky:lamoncloa.gob.es','kind':'bluesky','name':'La Moncloa','handle':'lamoncloa.gob.es','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':True},
 {'id':'bluesky:interior.gob.es','kind':'bluesky','name':'Ministerio del Interior','handle':'interior.gob.es','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':True},
 {'id':'mastodon:elpais@mastodon.social','kind':'mastodon','name':'El País','url':'https://mastodon.social/@elpais.rss','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':False},
 {'id':'mastodon:eldiario@mastodon.social','kind':'mastodon','name':'elDiario.es','url':'https://mastodon.social/@eldiario.rss','topics':['frontera_sur','protestas_juveniles','elecciones_generales','infraestructuras_espana'],'official':False},
]
def now(): return datetime.now(timezone.utc)
def clean(s): return ' '.join(html.unescape(re.sub(r'<[^>]+>',' ',str(s or ''))).split())
def relevant(topic,text): return any(x in text.lower() for x in TOPICS[topic]['terms'])
def parse_date(s):
 try:
  d=parsedate_to_datetime(s); return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
 except Exception: return None
def db():
 c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); return c
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':UA})
 with urllib.request.urlopen(req,timeout=15) as r: return r.read()
def telegram(src):
 raw=get('https://t.me/s/'+src['handle']).decode('utf-8','replace'); out=[]
 for block in re.split(r'<div class="tgme_widget_message_wrap',raw)[1:]:
  m=re.search(r'data-post="([^"]+)"',block); t=re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',block,re.S); d=re.search(r'<time[^>]*datetime="([^"]+)"',block)
  if not m or not t: continue
  text=clean(t.group(1)); link='https://t.me/'+m.group(1); pub=parse_date(d.group(1)) if d else None
  if text: out.append((text,link,pub))
 return out
def bluesky(src):
 raw=get('https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor='+src['handle']+'&limit=20'); d=json.loads(raw); out=[]
 for x in d.get('feed',[]):
  p=x.get('post',{}); rec=p.get('record',{}); text=clean(rec.get('text')); uri=p.get('uri',''); pub=parse_date(rec.get('createdAt'))
  if not text or not uri: continue
  rk=uri.rsplit('/',1)[-1]; out.append((text,'https://bsky.app/profile/'+src['handle']+'/post/'+rk,pub))
 return out
def mastodon(src):
 raw=get(src['url']); root=ET.fromstring(raw); out=[]
 for it in root.findall('./channel/item'):
  text=clean(it.findtext('title') or it.findtext('description')); link=(it.findtext('link') or '').strip(); pub=parse_date(it.findtext('pubDate'))
  if text and link: out.append((text,link,pub))
 return out
def run():
 c=db(); added=0; health={}; cutoff=now()-timedelta(days=45)
 for src in SOURCES:
  try:
   rows=telegram(src) if src['kind']=='telegram' else bluesky(src) if src['kind']=='bluesky' else mastodon(src)
  except Exception as e:
   health[src['id']]={'name':src['name'],'kind':src['kind'],'status':'error','error':str(e)[:160],'items':0}; continue
  n=0
  for text,link,pub in rows:
   if not pub or pub<cutoff: continue
   for topic in src['topics']:
    if not relevant(topic,text): continue
    iid=hashlib.sha256((topic+'|'+link).encode()).hexdigest()[:24]
    cur=c.execute('INSERT OR IGNORE INTO items(id,topic,title,url,source,published,query,fetched,source_type) VALUES(?,?,?,?,?,?,?,?,?)',(iid,topic,text[:500],link,src['name'],pub.isoformat(),'social:'+src['id'],now().isoformat(timespec='seconds'),'official' if src.get('official') else 'media'))
    added+=cur.rowcount; n+=cur.rowcount
  health[src['id']]={'name':src['name'],'kind':src['kind'],'status':'ok','items':n}
 c.commit(); c.close()
 TOKEN_DB.parent.mkdir(parents=True,exist_ok=True); tmp=TOKEN_DB.with_suffix('.tmp'); tmp.write_text(json.dumps({'updated_at':now().isoformat(timespec='seconds'),'sources':list(health.values())},ensure_ascii=False,indent=2)+'\n'); tmp.replace(TOKEN_DB)
 print(json.dumps({'added':added,'sources':len(health),'errors':sum(1 for x in health.values() if x['status']=='error')},ensure_ascii=False))
 return 0
if __name__=='__main__': raise SystemExit(run())
