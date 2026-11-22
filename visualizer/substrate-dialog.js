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
const pointRepeat=document.getElementById('pointRepeatCount');
const lineSettings=document.getElementById('lineTestSettings');
const lineLength=document.getElementById('lineLength');
const lineDepth=document.getElementById('lineDepth');
const lineRoundTrip=document.getElementById('lineRoundTrip');
const lineRepeat=document.getElementById('lineRepeatCount');
const lineZStep=document.getElementById('lineZStep');
const lineSpeed=document.getElementById('lineSpeed');
const circleSettings=document.getElementById('circleTestSettings');
const circleRadius=document.getElementById('circleRadius');
const circleSpeed=document.getElementById('circleSpeed');
const circleRepeat=document.getElementById('circleRepeatCount');
const circleFocus=document.getElementById('circleFocusOffset');
const isPoint=()=>select.value==='point';
const isLine=()=>select.value==='line';
const isCircle=()=>select.value==='circle';
let busy=false,watch=false,polling=false;
const mode=()=>document.getElementById('jogDryRun').checked?'mock':'live';
const speed=()=>Number(document.getElementById('travelRate').value);
function confirmAction(options){
 if(typeof window.flwConfirmPageAction!=='function')throw Error('앱 확인창이 아직 준비되지 않았습니다. 페이지를 새로고침한 뒤 다시 시도하세요.');
 return window.flwConfirmPageAction(options);
}
const lineFields=[lineLength,lineDepth,lineRoundTrip,lineRepeat,lineZStep,lineSpeed];
function disable(value){for(const b of [run,set,go,select,pointDepth,pointSpeed,pointRepeat,...lineFields,circleRadius,circleSpeed,circleRepeat,circleFocus])b.disabled=value;}
function pointSummary(){
 const depth=Number(pointDepth.value),speed=Number(pointSpeed.value),repeats=Number(pointRepeat.value);
 return `현재 Z에서 +${depth} mm를 ${speed} mm/s로 진입한 뒤 시작 Z까지 1 mm/s로 복귀합니다. 이 왕복을 ${repeats}회 반복합니다. X/Y 이동 없음. 예상 ${Number.isFinite(depth/speed)&&speed>0&&Number.isSafeInteger(repeats)&&repeats>0?Math.round((depth/speed+depth)*repeats):'—'}초.`;
}
function lineParameters(){
 const length=Number(lineLength.value),repeats=Number(lineRepeat.value),step=Number(lineZStep.value),velocity=Number(lineSpeed.value);
 const depth=Number(lineDepth.value);
 if(!Number.isFinite(length)||Math.abs(length)<0.001)throw Error('한쪽 길이의 절댓값은 0.001 mm 이상으로 입력하세요.');
 if(!Number.isSafeInteger(repeats)||repeats<1||repeats>10000)throw Error('반복횟수는 1–10000의 정수로 입력하세요.');
 if(lineDepth.value.trim()===''||!Number.isFinite(depth)||depth<0||(depth>0&&depth<0.001))throw Error('시작 진입 깊이는 0 또는 0.001 mm 이상으로 입력하세요.');
 if(lineZStep.value.trim()===''||!Number.isFinite(step)||step<0||(step>0&&step<0.001))throw Error('Z+ 이동은 0 또는 0.001 mm 이상으로 입력하세요.');
 if(!Number.isFinite(velocity)||velocity<0.01||velocity>10)throw Error('Y 이동 속도는 0.01–10 mm/s로 입력하세요.');
 return {length_mm:length,depth_mm:depth,round_trip:lineRoundTrip.checked,repeat_count:repeats,z_step_mm:step,xy_speed:velocity};
}
function lineSummary(){
 try{
  const {length_mm:length,depth_mm:depth,round_trip:back,repeat_count:n,z_step_mm:step,xy_speed:v}=lineParameters();
  const direction=length>0?'Y−':'Y+',distance=Math.abs(length);
  const zTravel=back?2*(depth+(n-1)*step):2*n*depth+n*(n-1)*step;
  const seconds=2*distance*n/v+zTravel;
  const end=back?'왕복 · 같은 깊이에서 시작 Y로 복귀':'편도 · 끝점에서 시작 Z 복귀 → 시작 Y 복귀';
  return `Z+ ${depth} mm 진입 → ${direction} ${distance} mm (${v} mm/s). ${end}. 같은 선을 ${n}회 가공하며 회차마다 진입 깊이가 ${step} mm씩 증가합니다. 완료 위치는 시작 XYZ입니다 (Z 1 mm/s). 예상 ${Number(seconds.toFixed(2))}초.`;
 }catch(e){return e.message;}
}
function circleSummary(){
 const radius=Number(circleRadius.value),velocity=Number(circleSpeed.value),repeats=Number(circleRepeat.value),offset=Number(circleFocus.value);
 return `현재 XY 중심 · 반지름 ${radius} mm (지름 ${2*radius} mm) · XY ${velocity} mm/s · Z+ ${offset} mm를 한 번 이동 후 같은 높이에서 ${repeats}회 회전 (X+ → Y+ 방향). 완료 후 시작 XYZ 복귀. Z 1 mm/s.`;
}
function renderSelection(){
 pointSettings.hidden=!isPoint();lineSettings.hidden=!isLine();circleSettings.hidden=!isCircle();set.hidden=isPoint()||isLine()||isCircle();go.hidden=isPoint()||isLine()||isCircle();
 if(isPoint())reference.textContent=pointSummary();
 else if(isLine())reference.textContent=lineSummary();
 else if(isCircle())reference.textContent=circleSummary();
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
   const depth=Number(pointDepth.value),ingress=Number(pointSpeed.value),repeats=Number(pointRepeat.value);
   if(!Number.isFinite(depth)||depth<=0)throw Error('깊이를 0보다 큰 값으로 입력하세요.');
   if(!Number.isFinite(ingress)||ingress<0.01||ingress>10)throw Error('진입 속도는 0.01–10 mm/s로 입력하세요.');
   if(!Number.isSafeInteger(repeats)||repeats<1)throw Error('반복횟수는 1 이상의 정수로 입력하세요.');
   action='point-run';body={mode:mode(),depth_mm:depth,ingress_speed:ingress,repeat_count:repeats};
  }else if(action==='run'&&isLine()){
   action='line-path-run';body={mode:mode(),...lineParameters()};
  }else if(action==='run'&&isCircle()){
   const radius=Number(circleRadius.value),velocity=Number(circleSpeed.value),repeats=Number(circleRepeat.value),offset=Number(circleFocus.value);
   if(!Number.isFinite(radius)||radius<0.001)throw Error('반지름은 0.001 mm 이상으로 입력하세요.');
   if(!Number.isFinite(velocity)||velocity<0.01||velocity>10)throw Error('XY Speed는 0.01–10 mm/s로 입력하세요.');
   if(!Number.isSafeInteger(repeats)||repeats<1||repeats>1000)throw Error('반복횟수는 1–1000의 정수로 입력하세요.');
   if(circleFocus.value.trim()===''||!Number.isFinite(offset)||offset<0||(offset>0&&offset<0.001))throw Error('초점까지 Z+ 이동은 0 또는 0.001 mm 이상으로 입력하세요.');
   action='circle-run';body={mode:mode(),radius_mm:radius,xy_speed:velocity,repeat_count:repeats,focus_offset_mm:offset};
  }else if(action==='set-upper-right'){
   if(!(await confirmAction({title:'Set upper-right',summary:'현재 위치를 substrate 우측 상단·Z 초점 기준으로 저장합니다. 스테이지 이동 없이 기존 local home을 유지합니다. 이후 경로는 등록 기준에서 X·Y 양의 방향으로 9.6 × 9.6 mm입니다.',acceptLabel:'현재 위치 등록',live:false})))return;
  }else if(action==='go-upper-right'){
   if(!(await confirmAction({title:'Go to upper-right',summary:'등록한 기준 Z보다 0.5 mm 낮은 위치로 이동한 뒤 XY를 우측 상단으로 복귀하고 마지막으로 기준 Z로 돌아갑니다. XY 속도 '+speed()+' mm/s. 이동 경로를 확인하세요.',live:mode()==='live'})))return;
  }
  await request(action,body);
  if(action==='set-upper-right')status.textContent='Upper-right 등록 완료 · 기존 local home 유지';
  else {watch=true;status.textContent=action==='circle-run'?'Circle 실행 중 — 기존 Stop run으로 중지':action==='line-path-run'?'Line 실행 중 — 기존 Stop run으로 중지':action==='point-run'?'Point 실행 중 — 기존 Stop run으로 중지':action==='run'?'Substrate 실행 중 — 기존 Stop run으로 중지':'Upper-right 복귀 중 — 기존 Stop run으로 중지';}
 }catch(e){status.textContent=e.message;}
 finally{busy=false;disable(watch);}
}
set.addEventListener('click',()=>perform('set-upper-right'));
go.addEventListener('click',()=>perform('go-upper-right'));
run.addEventListener('click',()=>perform('run'));
select.addEventListener('change',()=>{renderSelection();poll();});
for(const field of [pointDepth,pointSpeed,pointRepeat])field.addEventListener('input',()=>{if(isPoint())reference.textContent=pointSummary();});
for(const field of lineFields)field.addEventListener('input',()=>{if(isLine())reference.textContent=lineSummary();});
for(const field of [circleRadius,circleSpeed,circleRepeat,circleFocus])field.addEventListener('input',()=>{if(isCircle())reference.textContent=circleSummary();});
async function poll(){
 if(polling||busy)return;polling=true;
 try{
  const data=await request('status');
  reference.textContent=isPoint()?pointSummary():isLine()?lineSummary():isCircle()?circleSummary():data.upper_right?'Upper-right: '+data.upper_right.map((v,i)=>'XYZ'[i]+' '+v.toFixed(3)).join(' / ')+' mm · X·Y 양의 방향으로 진행':'Upper-right 미등록 · 연결·좌표 설정 변경 후에는 다시 등록하세요.';
  if(watch){const s=data.state;status.textContent=`${data.mode}: ${s.completed}/${s.total||48} · ${s.status} · ${s.phase||''} ${s.error||''}`;
   if(s.status!=='running'){watch=false;disable(false);}}
 }catch(e){if(watch)status.textContent='상태 확인 실패. 기존 Stop run/연결 상태를 확인하세요: '+e.message;}
 finally{polling=false;}
}
renderSelection();setInterval(poll,800);poll();
})();
