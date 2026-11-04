'use strict';
let recipe=JSON.parse(document.getElementById('recipe').textContent), liveContext=false;
const status=document.getElementById('status');
async function post(path,payload){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw Error(data.error||response.statusText);return data;}
if(location.protocol==='file:'){document.getElementById('refresh').disabled=true;document.getElementById('validate').disabled=true;}
document.getElementById('refresh').onclick=async()=>{try{recipe=await post('/api/depth/preview',{});liveContext=true;status.textContent='현재 원점 스냅샷으로 재생성됨. 실행은 금지되어 있습니다. 원점·축·설정 변경 시 다시 생성해야 합니다.';}catch(e){status.textContent=e.message;}};
async function validate(){const result=await post('/api/depth/validate',{recipe});status.textContent=result.reason;return result.valid;}
document.getElementById('validate').onclick=async()=>{try{await validate();}catch(e){status.textContent=e.message;}};
document.getElementById('download').onclick=async()=>{try{if(liveContext && !await validate())return;const url=URL.createObjectURL(new Blob([JSON.stringify(recipe,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='offline-depth-recipe.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){status.textContent=e.message;}};
