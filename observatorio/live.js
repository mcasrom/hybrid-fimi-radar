(function(){
  const boxes=document.querySelectorAll('.livebox[data-live-topic]');
  if(!boxes.length) return;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=s=>{try{return new Date(s).toLocaleString('es-ES',{dateStyle:'medium',timeStyle:'short'})}catch(e){return s||''}};
  function render(box,dto,filter){
    const all=dto.items||[];
    const es=all.filter(x=>!x.source_lang||x.source_lang==='es');
    const intl=all.filter(x=>x.source_lang&&x.source_lang!=='es');
    let items, label;
    if(filter==='es'){items=es.slice(0,8);label='Cobertura española';}
    else if(filter==='intl'){items=intl.slice(0,8);label='Mirada internacional';}
    else{items=[...es.slice(0,4),...intl.slice(0,4)];label='Muestra mixta';}
    const li=items.map(x=>`<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a><br><span class="live-meta">${esc(x.source||'')} · <b>${esc((x.source_lang||'es').toUpperCase())}</b>${x.source_type==='official'?' · <b>oficial</b>':''} · ${fmt(x.published)}</span></li>`).join('');
    const active=f=>filter===f?' on':'';
    box.innerHTML=`<div class="live-head"><h2>Publicaciones capturadas</h2><span class="live-meta">${dto.count} publicaciones · ${dto.sources} fuentes · ${fmt(d.updated_at)}</span></div><div class="livefilters"><button type="button" class="lfbtn${active('all')}" data-lf="all">Mixta</button><button type="button" class="lfbtn${active('es')}" data-lf="es">España</button><button type="button" class="lfbtn${active('intl')}" data-lf="intl">Internacional</button></div><p class="live-note"><b>${label}.</b> Captura automática de Google News + 89 feeds directos (ES/MA/DZ/FR/UK/RU/CN). Son titulares publicados, no hechos verificados. <a href="/observatorio/metodo/">Método</a></p>${items.length?'<ul class="live-list">'+li+'</ul>':'<p class="live-meta">Sin publicaciones en esta selección.</p>'}`;
    box.querySelectorAll('.lfbtn').forEach(b=>b.onclick=()=>render(box,dto,b.dataset.lf));
  }
  fetch('/observatorio/data/latest.json?x='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{boxes.forEach(box=>{const dto=(d.topics||{})[box.dataset.liveTopic];if(dto)render(box,dto,'all')})}).catch(()=>{boxes.forEach(b=>b.innerHTML='<p class="live-meta">No se pudo cargar la captura automática.</p>')});
})();
