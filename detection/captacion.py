#!/usr/bin/env python3
"""detection/captacion.py — Bloque de captación (newsletter) reutilizable.

Formulario self-contained que hace fetch POST a /api/subscribe (doble opt-in,
frecuencia semanal) para incrustar en páginas con tráfico humano (casos,
informes visuales, etc.). Devuelve HTML+JS con `temas` ya inyectados.

El HTML se construye aquí como plantilla NO-f-string con `{}` literales y se
inserta en el llamante como un valor, de modo que sus llaves no se reevalúan.
"""
from __future__ import annotations

import json

_TPL = """<div id="captacionFimi" style="margin:22px 0;padding:16px 18px;background:#fff7ed;border:1px solid #fdba74;border-left:5px solid #c2410c;border-radius:10px">
  <div style="font-weight:800;color:#7c2d12;font-size:1.02rem">📡 Te aviso cuando suba la banda de tus temas</div>
  <p style="margin:6px 0;color:#475569;font-size:.9rem"><b>Solo cuando hay señal</b> (banda alta) en los temas que elijas, más un <b>resumen cada lunes</b>. Sin ruido; baja en un clic.</p>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <input id="capEmail" type="email" placeholder="tu@correo.com" aria-label="Tu correo electrónico" style="flex:1;min-width:200px;padding:9px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:.9rem">
    <button id="capBtn" type="button" onclick="fimiSub()" style="background:#c2410c;color:#fff;border:none;border-radius:8px;padding:9px 18px;font-weight:700;cursor:pointer">Suscribirme</button>
  </div>
  <div id="capMsg" role="status" style="font-size:.82rem;color:#64748b;margin-top:6px"></div>
  <div style="font-size:.72rem;color:#94a3b8;margin-top:4px">Doble opt-in (te llega un correo para confirmar). Sin cesión a terceros.</div>
</div>
<script>
(function(){
  var TEMAS=__TEMAS__;
  window.fimiSub=function(){
    var e=document.getElementById('capEmail'),b=document.getElementById('capBtn'),m=document.getElementById('capMsg');
    var v=((e&&e.value)||'').trim();
    if(v.indexOf('@')<0){m.textContent='Escribe un correo válido.';m.style.color='#dc2626';return;}
    b.disabled=true;m.textContent='Enviando…';m.style.color='#64748b';
    fetch('/api/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:v,temas:TEMAS,frecuencia:'semanal',proyecto:'__PROYECTO__'})})
      .then(function(r){return r.json().catch(function(){return {};}).then(function(d){return {ok:r.ok,d:d};});})
      .then(function(x){
        if(x.ok&&x.d&&x.d.ok){m.textContent='✅ Revisa tu correo para confirmar la suscripción.';m.style.color='#16a34a';if(e)e.disabled=true;b.textContent='Hecho';}
        else {b.disabled=false;m.textContent='No se pudo: '+((x.d&&x.d.error)||'inténtalo más tarde');m.style.color='#dc2626';}
      })
      .catch(function(){b.disabled=false;m.textContent='Error de red. Inténtalo de nuevo.';m.style.color='#dc2626';});
  };
})();
</script>"""


def captacion_block(temas, proyecto="fimi"):
    """Devuelve el bloque HTML+JS. `temas` = lista de slugs (no vacía)."""
    temas = [str(t) for t in (temas or []) if str(t).strip()] or ["frontera_sur"]
    return _TPL.replace("__TEMAS__", json.dumps(temas)).replace("__PROYECTO__", str(proyecto))


if __name__ == "__main__":
    print(captacion_block(["frontera_sur"]))
