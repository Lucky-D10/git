// One 800×480 composition for kiosks and desktop. Narrow phones reflow normally.
// This changes presentation only; device/control clocks remain in the backend.
function sizeFrame(){
 const shell=document.getElementById('app-shell'),frame=document.getElementById('app-frame');
 frame.style.height=(shell.offsetHeight*(window.focusLayout?.scale||1))+'px';
}
export function fitLayout(){
 const wide=innerWidth>=700,padding=innerWidth>=1100?24:0;
 const scale=wide?Math.min(1.8,(innerWidth-padding*2)/800,Math.max(480,innerHeight-padding*2)/480):1;
 const top=wide?Math.max(padding,(innerHeight-480*scale)/2):0;
 const root=document.documentElement;
 root.style.setProperty('--app-scale',String(scale));root.style.setProperty('--frame-top',top+'px');
 document.body.dataset.framed=wide&&innerWidth>850?'true':'false';
 const shell=document.getElementById('app-shell');
 shell.dataset.layout=wide?'landscape':'phone';
 // Render canvases at the physical display density, including the UI scale.
 window.focusLayout={scale,width:wide?800:innerWidth,height:480,viewport:[innerWidth,innerHeight]};
 sizeFrame();
}
fitLayout();
window.addEventListener('resize',fitLayout);
new ResizeObserver(sizeFrame).observe(document.getElementById('app-shell'));
