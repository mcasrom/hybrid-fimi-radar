(function(){
  const boxes=document.querySelectorAll('.livebox[data-live-topic]');
  if(!boxes.length) return;
  fetch('/observatorio/data/latest.json?x='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
    boxes.forEach(box=>{
      const t=box.dataset.liveTopic, dto=(d.topics||{})[t]; if(!dto)return;
      const items=(dto.items||[]).slice(0,8);
      const li=items.map(x=>`<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a><br><span class="live-meta">${esc(x.source||'')} · ${fmt(x.published)}</span></li>`).join('');
      box.innerHTML=`<div class="live-head"><h2>Publicaciones capturadas</h2><span class="live-meta">${dto.count} publicaciones · ${dto.sources} fuentes · ${fmt(d.updated_at)}</span></div><p class="live-note">Captura automática de Google News + 75 feeds directos (ES/MA/DZ/FR/UK/RU/CN). Son titulares publicados, no hechos verificados. <a href="/observatorio/metodo/">Método</a></p>${items.length?'<ul class="live-list">'+li+'</ul>':'<p class="live-meta">Sin publicaciones en la ventana actual.</p>'}`;
    });
  }).catch(e=>{boxes.forEach(b=>b.innerHTML='<p class="live-meta">No se pudo cargar la captura automática.</p>')});
  function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  function fmt(s){try{return new Date(s).toLocaleString('es-ES',{dateStyle:'medium',timeStyle:'short'})}catch(e){return s||''}}
})();
