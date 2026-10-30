#!/usr/bin/env python3
import json, sqlite3, subprocess
from datetime import datetime, timezone
from pathlib import Path
WEB=Path('/var/www/fimi/observatorio')
OUT=WEB/'admin'/'status.json'
def read_json(p):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return {}
res=read_json(WEB/'data'/'resumen.json')
subs={'pending':0,'confirmed':0,'unsubscribed':0,'total':0}
db=Path('/home/deploy/observatorio/data/subs.db')
if db.exists():
    try:
        con=sqlite3.connect(f'file:{db}?mode=ro',uri=True); con.row_factory=sqlite3.Row
        for r in con.execute("select status,count(*) n from subscribers group by status"):
            subs[r['status']]=r['n']
        subs['total']=sum(v for k,v in subs.items() if k!='total')
        con.close()
    except Exception as exc:
        subs['error']=str(exc)
pages={}
for name,path in [('home','/'),('ceuta','/observatorio/ceuta/'),('juventud','/observatorio/juventud/'),('campana','/observatorio/campana/'),('infraestructuras','/observatorio/infraestructuras/'),('metodo','/observatorio/metodo/'),('fuentes','/observatorio/fuentes/'),('datos','/observatorio/datos/'),('ayuda','/observatorio/ayuda/'),('suscribirse','/observatorio/suscribirse/')]:
    pages[name]=200 if (Path('/var/www/fimi')/(path.strip('/') or 'index.html')).exists() or path=='/' else 404
status={
 'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
 'content':{'temas':4,'fichas':12,'fuentes':res.get('fuentes_unicas',0),'primarias':0,'fichas_ceuta':res.get('ceuta',{}).get('fichas',0),'episodios_juventud':res.get('juventud',{}).get('episodios',0),'hitos_campana':res.get('campana',{}).get('hitos',0)},
 'subscriptions':subs,
 'pages':pages,
 'notes':['Sin propuestas ni comentarios públicos: no hay formulario abierto.','La lista antigua de FIMI no se ha migrado.'],
}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(OUT)
