(function(){
  const boxes=document.querySelectorAll('.livebox[data-live-topic]');
  if(!boxes.length) return;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=s=>{try{return new Date(s).toLocaleString('es-ES',{dateStyle:'medium',timeStyle:'short'})}catch(e){return s||''}};
  const SECTOR_LABELS={ferrocarril:'Ferrocarril',carretera:'Carretera',puerto:'Puerto',aeropuerto:'Aeropuerto',agua:'Agua',energia:'Energía',otro:'Otro'};
  function render(box,dto,filter,updatedAt,topicStatus,sector){
    sector=sector||'all';
    const all=dto.items||[];
    const es=all.filter(x=>!x.source_lang||x.source_lang==='es');
    const intl=all.filter(x=>x.source_lang&&x.source_lang!=='es');
    let items, label;
    if(filter==='es'){items=es.slice(0,8);label='Cobertura española';}
    else if(filter==='intl'){items=intl.slice(0,8);label='Mirada internacional';}
    else{items=[...es.slice(0,4),...intl.slice(0,4)];label='Muestra mixta';}
    const isInfra=box.dataset.liveTopic==='infraestructuras_espana';
    if(isInfra && sector!=='all') items=items.filter(x=>x.infra_type===sector).slice(0,8);
    const li=items.map(x=>{
      const meta=[esc(x.source||''),'<b>'+esc((x.source_lang||'es').toUpperCase())+'</b>'];
      if(x.source_type==='official') meta.push('<b>oficial</b>');
      if(x.source_class==='state') meta.push('<b>estatal</b>');
      if(x.infra_type) meta.push('<b>'+esc(SECTOR_LABELS[x.infra_type]||x.infra_type)+'</b>');
      if(x.operator && x.operator!=='No consta') meta.push(esc(x.operator));
      meta.push(fmt(x.published));
      return `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a><br><span class="live-meta">${meta.join(' · ')}</span></li>`;
    }).join('');
    const active=f=>filter===f?' on':'';
    const st=topicStatus||{};
    const langTxt=Object.entries(st.languages||{}).slice(0,6).map(([k,v])=>`${String(k).toUpperCase()} ${v}`).join(' · ');
    const statusLine=st.count_45d?`<p class="live-meta"><b>45 d:</b> ${st.count_45d} publicaciones · ${st.sources} fuentes · ${st.official_pct}% oficial · ${st.state_pct}% estatal${langTxt?' · '+langTxt:''}</p>`:'';
    const sectorButtons=isInfra?`<div class="livefilters"><button type="button" class="lfbtn${sector==='all'?' on':''}" data-sector="all">Todos</button>${Object.entries(SECTOR_LABELS).map(([k,v])=>`<button type="button" class="lfbtn${sector===k?' on':''}" data-sector="${k}">${v}</button>`).join('')}</div>`:'';
    box.innerHTML=`<div class="live-head"><h2>Publicaciones capturadas</h2><span class="live-meta">${dto.count} publicaciones · ${dto.sources} fuentes · ${fmt(updatedAt)}</span></div><div class="livefilters"><button type="button" class="lfbtn${active('all')}" data-lf="all">Mixta</button><button type="button" class="lfbtn${active('es')}" data-lf="es">España</button><button type="button" class="lfbtn${active('intl')}" data-lf="intl">Internacional</button></div>${sectorButtons}<p class="live-note"><b>${label}.</b> Captura automática de Google News + feeds directos (ES/MA/DZ/FR/UK/RU/CN). Son titulares publicados, no hechos verificados. <a href="/observatorio/metodo/">Método</a></p>${statusLine}${items.length?'<ul class="live-list">'+li+'</ul>':'<p class="live-meta">Sin publicaciones en esta selección.</p>'}`;
    box.querySelectorAll('.lfbtn[data-lf]').forEach(b=>b.onclick=()=>render(box,dto,b.dataset.lf,updatedAt,topicStatus,sector));
    box.querySelectorAll('.lfbtn[data-sector]').forEach(b=>b.onclick=()=>render(box,dto,filter,updatedAt,topicStatus,b.dataset.sector));
  }
  fetch('/observatorio/data/latest.json?x='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{boxes.forEach(box=>{const dto=(d.topics||{})[box.dataset.liveTopic];if(dto)render(box,dto,'all',d.updated_at,(d.status&&d.status.topics||{})[box.dataset.liveTopic])})}).catch(err=>{console.error('live.js',err);boxes.forEach(b=>b.innerHTML='<p class="live-meta">No se pudo cargar la captura automática.</p>')});
})();
