(function(){
  const root=document.documentElement;
  try{const s=localStorage.getItem('obs_theme'); if(s) root.dataset.theme=s; else if(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches) root.dataset.theme='dark';}catch(e){}
  if(!document.querySelector('link[href="/observatorio/theme.css"]')){const l=document.createElement('link');l.rel='stylesheet';l.href='/observatorio/theme.css';document.head.appendChild(l);}
  function add(){
    let b=document.getElementById('themeToggle');
    if(!b){
      const head=document.querySelector('.obs-actions')||document.querySelector('.sitehead');
      if(head){b=document.createElement('button');b.id='themeToggle';b.type='button';b.className='obs-theme';head.appendChild(b);}
    }
    if(b){
      const set=()=>{b.textContent=root.dataset.theme==='dark'?'Claro':'Oscuro';b.setAttribute('aria-label',root.dataset.theme==='dark'?'Cambiar a tema claro':'Cambiar a tema oscuro');};
      b.onclick=()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem('obs_theme',root.dataset.theme)}catch(e){}set();};
      set();
    }
    const head=document.querySelector('.obs-actions')||document.querySelector('.sitehead');
    if(head&&!document.getElementById('langToggle')){const a=document.createElement('a');a.id='langToggle';a.className='obs-lang';a.href='/observatorio/en/';a.lang='en';a.textContent='EN';a.setAttribute('aria-label','English version');a.title='English version';head.appendChild(a);}
    const foot=document.querySelector('.foot'); if(foot&&!foot.querySelector('.support')){const d=document.createElement('div');d.className='support';d.innerHTML='<b>Apoyar</b><a href="/observatorio/apoyo/">Ko-fi y transparencia →</a>';foot.appendChild(d);}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',add);else add();
})();
