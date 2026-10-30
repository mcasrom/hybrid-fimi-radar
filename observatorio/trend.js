(function(){
  const boxes=document.querySelectorAll('[data-trend-topic]'); if(!boxes.length) return;
  fetch('/observatorio/data/latest.json?x='+Date.now(),{cache:'no-store'}).then(r=>r.json()).then(d=>{
    boxes.forEach(box=>{
      const t=(d.topics||{})[box.dataset.trendTopic]; if(!t||!t.trend||!t.trend.length)return;
      const vals=t.trend.slice(-14), max=Math.max(...vals.map(x=>x.n)), w=180,h=30;
      const bars=vals.map((x,i)=>{const bw=w/vals.length; const bh=Math.max(2,(x.n/max)*(h-4)); return `<rect x="${i*bw+1}" y="${h-bh}" width="${Math.max(1,bw-2)}" height="${bh}" fill="#b45309"></rect>`}).join('');
      box.innerHTML=`<div class="mtlabel">Publicaciones/día · captura</div><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Publicaciones por día">${bars}</svg>`;
    });
  }).catch(()=>{});
})();
