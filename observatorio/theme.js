(function(){
  const root=document.documentElement;
  try{const s=localStorage.getItem('obs_theme'); if(s) root.dataset.theme=s; else if(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches) root.dataset.theme='dark';}catch(e){}
  if(!document.querySelector('link[href="/observatorio/theme.css"]')){const l=document.createElement('link');l.rel='stylesheet';l.href='/observatorio/theme.css';document.head.appendChild(l);}
  function add(){const head=document.querySelector('.sitehead');if(!head||document.getElementById('themeToggle'))return;const b=document.createElement('button');b.id='themeToggle';b.type='button';b.setAttribute('aria-label','Cambiar tema claro u oscuro');const set=()=>{b.textContent=root.dataset.theme==='dark'?'☀️':'🌙';};b.onclick=()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem('obs_theme',root.dataset.theme)}catch(e){}set();};set();head.appendChild(b);
  if(!document.getElementById('langToggle')){const a=document.createElement('a');a.id='langToggle';a.href='/observatorio/en/';a.lang='en';a.textContent='EN';a.setAttribute('aria-label','English version');a.title='English version';head.appendChild(a);}
  const foot=document.querySelector('.foot'); if(foot&&!foot.querySelector('.support')){const d=document.createElement('div');d.className='support';d.innerHTML='<b>Apoyar</b><a href="/observatorio/apoyo/">Ko-fi y transparencia →</a>';foot.appendChild(d);}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',add);else add();
})();
