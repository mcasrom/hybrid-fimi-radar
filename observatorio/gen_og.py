#!/usr/bin/env python3
from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
OUT=Path(__file__).resolve().parent
W,H=1200,630
FG='#f8fafc'; MUT='#cbd5e1'; AMB='#fbbf24'
def font(size,bold=False):
 for p in ['/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
  try:return ImageFont.truetype(p,size)
  except Exception:pass
 return ImageFont.load_default()
def make(name,eyebrow,title,metric,sub,accent):
 img=Image.new('RGB',(W,H),'#0f172a'); d=ImageDraw.Draw(img); d.rectangle([0,0,W,14],fill=accent)
 d.text((70,80),eyebrow,font=font(22,True),fill=AMB)
 d.text((70,150),title,font=font(62,True),fill=FG)
 d.text((70,300),metric,font=font(42,True),fill=accent)
 d.text((70,390),sub,font=font(28),fill=MUT)
 d.text((70,540),'fimi.viajeinteligencia.com/observatorio/',font=font(22),fill='#94a3b8')
 img.save(OUT/name,'PNG')
make('og-frontera-sur.png','FRONTERA SUR','Ceuta y Marruecos','6 fichas · 16 fuentes','Qué se publica, qué se confirma y qué falta','#b45309')
make('og-protestas.png','PROTESTAS JUVENILES','Movilizaciones juveniles','6 episodios · 10 fuentes','Fechas, ciudades, convocantes y demandas','#0f766e')
make('og-elecciones.png','ELECCIONES GENERALES','España — 29N','5 hitos oficiales','Calendario y seguimiento de campaña','#1d4ed8')
make('og-infraestructuras.png','INFRAESTRUCTURAS ESPAÑA','Alta velocidad y carreteras','Captura cada 30 minutos','Titulares y fuentes oficiales','#7c2d12')
make('og-eventos.png','ACONTECIMIENTOS','Frontera Sur','Publicaciones agrupadas','Candidatos, no hechos confirmados','#b45309')
print('ok')
