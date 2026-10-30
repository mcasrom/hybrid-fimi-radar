#!/usr/bin/env python3
"""Lee el real decreto de convocatoria del BOE y genera calendario_oficial.json."""
import argparse, json, re, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).with_name('calendario_oficial.json')
URL='https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-20742'
UA='Mozilla/5.0 (compatible; Observatorio/1.0)'

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=25) as r:
        return r.read()

def parse(xml_bytes):
    root=ET.fromstring(xml_bytes)
    def txt(tag):
        x=root.find('.//'+tag); return (x.text or '').strip() if x is not None else ''
    title=txt('titulo'); ident=txt('identificador')
    pub=txt('fecha_publicacion')
    body=' '.join(t for t in root.itertext()).replace('\xa0',' ').replace('\u2003',' ')
    election=re.search(r'domingo\s+(\d{1,2}) de noviembre de (\d{4})',body,re.I)
    camp=re.search(r'campaña electoral.*?cero horas del viernes\s+(\d{1,2}) de noviembre.*?veinticuatro horas del viernes\s+(\d{1,2}) de noviembre',body,re.I|re.S)
    const=re.search(r'Cámaras resultantes se reunirán.*?día\s+(\d{1,2}) de diciembre',body,re.I|re.S)
    if not (election and camp and const): raise ValueError('No se pudieron extraer las fechas del BOE')
    y=int(election.group(2)); election_day=date(y,11,int(election.group(1)))
    start=date(y,11,int(camp.group(1))); end=date(y,11,int(camp.group(2)))
    constitution=date(y,12,int(const.group(1)))
    assert election_day.weekday()==6, 'La fecha electoral no es domingo'
    assert start.weekday()==4 and end.weekday()==4, 'La campaña no empieza/termina en viernes'
    pub_date=datetime.strptime(pub,'%Y%m%d').date()
    return {
      'generated_at':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
      'source':{'documento':ident,'titulo':title,'url':URL,'fecha_publicacion':pub_date.isoformat(),'url_pdf':txt('url_pdf')},
      'hitos':[
        {'fecha':pub_date.isoformat(),'hito':'Publicación de la convocatoria','estado':'oficial','fuente':URL,'evidencia':title},
        {'fecha':start.isoformat(),'hito':'Inicio de la campaña electoral','estado':'oficial','fuente':URL,'evidencia':'Campaña electoral: del 13 al 27 de noviembre de 2026'},
        {'fecha':end.isoformat(),'hito':'Fin de la campaña electoral','estado':'oficial','fuente':URL,'evidencia':'Campaña electoral: del 13 al 27 de noviembre de 2026'},
        {'fecha':election_day.isoformat(),'hito':'Jornada electoral','estado':'oficial','fuente':URL,'evidencia':'Elecciones a Cortes Generales'},
        {'fecha':constitution.isoformat(),'hito':'Constitución de las Cámaras','estado':'oficial','fuente':URL,'evidencia':'Reunión constitutiva de las Cámaras'},
      ]
    }

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--fetch',action='store_true'); ap.add_argument('--url',default=URL); a=ap.parse_args()
    data=fetch(a.url) if a.fetch else (Path(__file__).with_name('fixtures')/'boe_rd806.xml').read_bytes()
    doc=parse(data); OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT)
if __name__=='__main__': main()
