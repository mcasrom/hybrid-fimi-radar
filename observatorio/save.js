(function(){
  const KEY='obs_saved_topics_v1';
  const read=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch(e){return []}};
  let saved=read();
  const paint=()=>{document.querySelectorAll('[data-save-topic]').forEach(b=>{const on=saved.includes(b.dataset.saveTopic);b.textContent=on?'★ Guardado':'☆ Guardar tema';b.setAttribute('aria-pressed',on?'true':'false');b.title='Se guarda solo en este navegador; no se envía al servidor.';});};
  document.addEventListener('click',e=>{const b=e.target.closest('[data-save-topic]');if(!b)return;e.preventDefault();e.stopPropagation();const t=b.dataset.saveTopic;if(saved.includes(t))saved=saved.filter(x=>x!==t);else saved.push(t);try{localStorage.setItem(KEY,JSON.stringify(saved))}catch(err){}paint();});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',paint);else paint();
})();
