"use strict";
(()=>{
const run=document.getElementById('substrateTestButton');
const set=document.getElementById('substrateSetUpperRightButton');
const go=document.getElementById('substrateGoUpperRightButton');
const status=document.getElementById('substrateStatusText');
const reference=document.getElementById('substrateReferenceText');
const select=document.getElementById('testSelect');
const pointSettings=document.getElementById('pointTestSettings');
const pointDepth=document.getElementById('pointDepth');
const pointSpeed=document.getElementById('pointIngressSpeed');
const isPoint=()=>select.value==='point';
let busy=false,watch=false,polling=false;
const mode=()=>document.getElementById('jogDryRun').checked?'mock':'live';
const speed=()=>Number(document.getElementById('travelRate').value);
function confirmAction(options){
 if(typeof window.flwConfirmPageAction!=='function')throw Error('앱 확인창이 아직 준비되지 않았습니다. 페이지를 새로고침한 뒤 다시 시도하세요.');
 return window.flwConfirmPageAction(options);
}
function disable(value){for(const b of [run,set,go,select,pointDepth,pointSpeed])b.disabled=value;}
function pointSummary(){
 const depth=Number(pointDepth.value),speed=Number(pointSpeed.value);
 return `현재 Z에서 +${depth} mm를 ${speed} mm/s로 진입한 뒤 시작 Z까지 1 mm/s로 복귀합니다. X/Y 이동 없음. 예상 ${Number.isFinite(depth/speed)&&speed>0?Math.round(depth/speed+depth):'—'}초.`;
}
function renderSelection(){
 pointSettings.hidden=!isPoint();set.hidden=isPoint();go.hidden=isPoint();
 if(isPoint())reference.textContent=pointSummary();
 else reference.textContent='Upper-right 상태 확인 중…';
}
async function request(action,body){
 const response=await fetch('/api/substrate/'+action,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const data=await response.json();if(!response.ok||data.error)throw Error(data.error||'요청 실패');return data;
}
async function perform(action){
 if(busy)return;busy=true;disable(true);
 try{
  let body={mode:mode(),xy_speed:speed()};
  if(action==='run'&&isPoint()){
   const depth=Number(pointDepth.value),ingress=Number(pointSpeed.value);
   if(!Number.isFinite(depth)||depth<=0)throw Error('깊이를 0보다 큰 값으로 입력하세요.');
   if(!Number.isFinite(ingress)||ingress<0.01||ingress>10)throw Error('진입 속도는 0.01–10 mm/s로 입력하세요.');
   action='point-run';body={mode:mode(),depth_mm:depth,ingress_speed:ingress};
  }else if(action==='set-upper-right'){
   if(!(await confirmAction({title:'Set upper-right',summary:'현재 위치를 substrate 우측 상단·Z 초점 기준으로 저장합니다. 스테이지 이동 없이 기존 local home을 유지합니다. 이후 경로는 등록 기준에서 X·Y 양의 방향으로 9.6 × 9.6 mm입니다.',acceptLabel:'현재 위치 등록',live:false})))return;
  }else if(action==='go-upper-right'){
   if(!(await confirmAction({title:'Go to upper-right',summary:'등록한 기준 Z보다 0.5 mm 낮은 위치로 이동한 뒤 XY를 우측 상단으로 복귀하고 마지막으로 기준 Z로 돌아갑니다. XY 속도 '+speed()+' mm/s. 이동 경로를 확인하세요.',live:mode()==='live'})))return;
  }
  await request(action,body);
  if(action==='set-upper-right')status.textContent='Upper-right 등록 완료 · 기존 local home 유지';
  else {watch=true;status.textContent=action==='point-run'?'Point 실행 중 — 기존 Stop run으로 중지':action==='run'?'Substrate 실행 중 — 기존 Stop run으로 중지':'Upper-right 복귀 중 — 기존 Stop run으로 중지';}
 }catch(e){status.textContent=e.message;}
 finally{busy=false;disable(watch);}
}
set.addEventListener('click',()=>perform('set-upper-right'));
go.addEventListener('click',()=>perform('go-upper-right'));
run.addEventListener('click',()=>perform('run'));
select.addEventListener('change',()=>{renderSelection();poll();});
for(const field of [pointDepth,pointSpeed])field.addEventListener('input',()=>{if(isPoint())reference.textContent=pointSummary();});
async function poll(){
 if(polling||busy)return;polling=true;
 try{
  const data=await request('status');
  reference.textContent=isPoint()?pointSummary():data.upper_right?'Upper-right: '+data.upper_right.map((v,i)=>'XYZ'[i]+' '+v.toFixed(3)).join(' / ')+' mm · X·Y 양의 방향으로 진행':'Upper-right 미등록 · 연결·좌표 설정 변경 후에는 다시 등록하세요.';
  if(watch){const s=data.state;status.textContent=`${data.mode}: ${s.completed}/${s.total||48} · ${s.status} · ${s.phase||''} ${s.error||''}`;
   if(s.status!=='running'){watch=false;disable(false);}}
 }catch(e){if(watch)status.textContent='상태 확인 실패. 기존 Stop run/연결 상태를 확인하세요: '+e.message;}
 finally{polling=false;}
}
renderSelection();setInterval(poll,800);poll();
})();
