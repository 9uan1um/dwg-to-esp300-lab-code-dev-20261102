// Hardware-free DOM contract test for the Select Test controls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = {};
for (const id of ['substrateTestButton','substrateSetUpperRightButton','substrateGoUpperRightButton',
 'substrateStatusText','substrateReferenceText','testSelect','pointTestSettings','pointDepth',
 'pointIngressSpeed','pointRepeatCount','jogDryRun','travelRate',
 'lineTestSettings','lineLength','lineDepth','lineRoundTrip','lineRepeatCount','lineZStep','lineSpeed',
 'circleTestSettings','circleRadius','circleSpeed','circleRepeatCount','circleFocusOffset']) {
 elements[id] = {value:'',hidden:false,disabled:false,textContent:'',events:{},
  addEventListener(event,callback){this.events[event]=callback;}};
}
Object.assign(elements.testSelect,{value:'substrate'});
Object.assign(elements.pointDepth,{value:'3'});
Object.assign(elements.pointIngressSpeed,{value:'0.01'});
Object.assign(elements.pointRepeatCount,{value:'1'});
Object.assign(elements.lineLength,{value:'1'});
Object.assign(elements.lineDepth,{value:'0'});
Object.assign(elements.lineRoundTrip,{checked:false});
Object.assign(elements.lineRepeatCount,{value:'1'});
Object.assign(elements.lineZStep,{value:'0'});
Object.assign(elements.lineSpeed,{value:'1'});
Object.assign(elements.circleRadius,{value:'1'});
Object.assign(elements.circleSpeed,{value:'1'});
Object.assign(elements.circleRepeatCount,{value:'1'});
Object.assign(elements.circleFocusOffset,{value:'0'});
Object.assign(elements.travelRate,{value:'2'});
Object.assign(elements.jogDryRun,{checked:true});
const calls=[], confirmations=[];
let state={status:'idle',completed:0}, accept=true;
const context={document:{getElementById:id=>elements[id]},setInterval:()=>{},
 window:{flwConfirmPageAction:async options=>{confirmations.push(options);return accept;}},
 fetch:async(url,options)=>{
  calls.push({url,body:options.body&&JSON.parse(options.body)});
  return {ok:true,json:async()=>({mode:'mock',state,upper_right:null})};
 }};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function main(){
 vm.runInNewContext(fs.readFileSync(__dirname+'/visualizer/substrate-dialog.js','utf8'),context);
 await settle();
 assert.equal(elements.pointTestSettings.hidden,true);
 elements.testSelect.value='point';elements.testSelect.events.change();await settle();
 assert.equal(elements.pointTestSettings.hidden,false);
 assert.equal(elements.substrateSetUpperRightButton.hidden,true);
 assert.equal(elements.substrateGoUpperRightButton.hidden,true);
 assert.match(elements.substrateReferenceText.textContent,/303초/);
 elements.substrateTestButton.events.click();await settle();
 assert.deepEqual(calls.find(c=>c.url.endsWith('/point-run')).body,
  {mode:'mock',depth_mm:3,ingress_speed:0.01,repeat_count:1});
 assert.equal(confirmations.length,0); // Point starts immediately, without a dialog.
 assert.equal(elements.testSelect.disabled,true);
 assert.equal(elements.pointRepeatCount.disabled,true);
 // Trigger the stored polling callback in a fresh VM to verify repeated progress and unlock.
 let poll;
 const second={...context,setInterval:callback=>{poll=callback;}};
 vm.runInNewContext(fs.readFileSync(__dirname+'/visualizer/substrate-dialog.js','utf8'),second);
 await settle();
 elements.pointDepth.value='2';elements.pointIngressSpeed.value='0.2';
 elements.pointRepeatCount.value='3';elements.pointRepeatCount.events.input();
 assert.match(elements.substrateReferenceText.textContent,/3회/);
 assert.match(elements.substrateReferenceText.textContent,/36초/);
 elements.substrateTestButton.events.click();await settle();
 assert.deepEqual(calls.at(-1).body,{mode:'mock',depth_mm:2,ingress_speed:0.2,repeat_count:3});
 state={status:'completed',completed:6,total:6,phase:'completed'};
 await poll();
 assert.match(elements.substrateStatusText.textContent,/6\/6/);
 assert.equal(elements.testSelect.disabled,false);
 assert.equal(elements.pointRepeatCount.disabled,false);
 let count=calls.length;
 elements.pointIngressSpeed.value='0.001';
 elements.substrateTestButton.events.click();await settle();
 assert.equal(calls.length,count);
 assert.match(elements.substrateStatusText.textContent,/0.01/);
 elements.pointIngressSpeed.value='0.01';
 for(const invalid of ['', '0', '-1', '1.5', 'abc']){
  elements.pointRepeatCount.value=invalid;
  elements.substrateTestButton.events.click();await settle();
  assert.equal(calls.length,count);
  assert.match(elements.substrateStatusText.textContent,/반복횟수/);
 }
 elements.pointRepeatCount.value='1';
 elements.testSelect.value='line';elements.testSelect.events.change();await settle();
 assert.equal(elements.lineTestSettings.hidden,false);
 assert.equal(elements.pointTestSettings.hidden,true);
 assert.equal(elements.substrateSetUpperRightButton.hidden,true);
 assert.equal(elements.substrateGoUpperRightButton.hidden,true);
 assert.match(elements.substrateReferenceText.textContent,/Y− 1 mm.*편도 · 끝점에서 시작 Z 복귀 → 시작 Y 복귀/);
 const html=fs.readFileSync(__dirname+'/visualizer/index.html','utf8');
 assert.match(html,/id="lineDepth"[^>]*value="0"/);
 assert.match(html,/id="lineRoundTrip" type="checkbox"\s*\/>/);
 assert.doesNotMatch(html.match(/<input id="lineLength"[^>]*>/)[0],/\bmin=/);
 elements.substrateTestButton.events.click();await settle();
 assert.deepEqual(calls.at(-1).body,{mode:'mock',length_mm:1,depth_mm:0,round_trip:false,repeat_count:1,z_step_mm:0,xy_speed:1});
 await poll();
 elements.lineLength.value='-2';elements.lineRepeatCount.value='3';elements.lineZStep.value='0.1';
 elements.lineDepth.value='0.5';
 elements.lineSpeed.value='0.5';elements.lineDepth.events.input();
 assert.match(elements.substrateReferenceText.textContent,/27.6초/);
 elements.lineRoundTrip.checked=true;
 elements.lineSpeed.value='0.5';elements.lineSpeed.events.input();
 assert.match(elements.substrateReferenceText.textContent,/Z\+ 0.5 mm 진입 → Y\+ 2 mm \(0.5 mm\/s\)/);
 assert.match(elements.substrateReferenceText.textContent,/왕복 · 같은 깊이에서 시작 Y로 복귀/);
 assert.match(elements.substrateReferenceText.textContent,/25.4초/);
 elements.substrateTestButton.events.click();await settle();
 assert.equal(calls.at(-1).url,'/api/substrate/line-path-run');
 assert.deepEqual(calls.at(-1).body,{mode:'mock',length_mm:-2,depth_mm:0.5,round_trip:true,repeat_count:3,z_step_mm:0.1,xy_speed:0.5});
 assert.equal(confirmations.length,0);
 const lineControls=['testSelect','lineLength','lineDepth','lineRoundTrip','lineRepeatCount','lineZStep','lineSpeed'];
 for(const id of lineControls)assert.equal(elements[id].disabled,true);
 state={status:'running',completed:3,total:12,phase:'line_z_step'};await poll();
 assert.match(elements.substrateStatusText.textContent,/3\/12.*line_z_step/);
 state={status:'completed',completed:12,total:12,phase:'completed'};await poll();
 assert.match(elements.substrateStatusText.textContent,/12\/12/);
 for(const id of lineControls)assert.equal(elements[id].disabled,false);
 count=calls.length;
 for(const [id,invalids] of [['lineLength',['','0','-0.0001','0.0001','abc']],
  ['lineDepth',['','-1','0.0001','abc']],
  ['lineRepeatCount',['','0','-1','1.5','10001']],['lineZStep',['','-1','0.0001','abc']],
  ['lineSpeed',['','0','0.001','11','abc']]]){
  const saved=elements[id].value;
  for(const invalid of invalids){
   elements[id].value=invalid;elements.substrateTestButton.events.click();await settle();
   assert.equal(calls.length,count,`${id}=${invalid} must not submit`);
  }
  elements[id].value=saved;
 }
 elements.testSelect.value='circle';elements.testSelect.events.change();await settle();
 assert.equal(elements.circleTestSettings.hidden,false);
 assert.equal(elements.lineTestSettings.hidden,true);
 assert.equal(elements.pointTestSettings.hidden,true);
 assert.equal(elements.substrateSetUpperRightButton.hidden,true);
 assert.equal(elements.substrateGoUpperRightButton.hidden,true);
 elements.circleRadius.value='0.3';elements.circleSpeed.value='0.5';
 elements.circleRepeatCount.value='3';elements.circleFocusOffset.value='0.2';
 elements.circleFocusOffset.events.input();
 assert.match(elements.substrateReferenceText.textContent,/반지름 0.3 mm/);
 assert.match(elements.substrateReferenceText.textContent,/한 번 이동 후 같은 높이에서 3회/);
 elements.substrateTestButton.events.click();await settle();
 assert.equal(calls.at(-1).url,'/api/substrate/circle-run');
 assert.deepEqual(calls.at(-1).body,{mode:'mock',radius_mm:0.3,xy_speed:0.5,repeat_count:3,focus_offset_mm:0.2});
 assert.equal(confirmations.length,0);
 for(const id of ['testSelect','circleRadius','circleSpeed','circleRepeatCount','circleFocusOffset'])assert.equal(elements[id].disabled,true);
 state={status:'running',completed:2,total:544,phase:'circle_trace'};await poll();
 assert.match(elements.substrateStatusText.textContent,/2\/544.*circle_trace/);
 state={status:'completed',completed:544,total:544,phase:'completed'};await poll();
 for(const id of ['testSelect','circleRadius','circleSpeed','circleRepeatCount','circleFocusOffset'])assert.equal(elements[id].disabled,false);
 count=calls.length;
 for(const [id,invalids] of [['circleRadius',['','0','-1','0.0001','abc']],
  ['circleRepeatCount',['','0','-1','1.5','1001']],['circleFocusOffset',['','-1','0.0001','abc']],
  ['circleSpeed',['','0','0.001','11','abc']]]){
  const saved=elements[id].value;
  for(const invalid of invalids){
   elements[id].value=invalid;elements.substrateTestButton.events.click();await settle();
   assert.equal(calls.length,count,`${id}=${invalid} must not submit`);
  }
  elements[id].value=saved;
 }
 elements.jogDryRun.checked=false;elements.circleFocusOffset.value='0';
 elements.substrateTestButton.events.click();await settle();
 assert.equal(calls.at(-1).body.mode,'live');
 assert.equal(calls.at(-1).body.focus_offset_mm,0);
 await poll();elements.jogDryRun.checked=true;
 elements.travelRate.value='2';
 elements.testSelect.value='substrate';elements.testSelect.events.change();await settle();
 assert.equal(elements.substrateSetUpperRightButton.hidden,false);
 assert.equal(elements.pointTestSettings.hidden,true);
 assert.equal(elements.lineTestSettings.hidden,true);
 assert.equal(elements.circleTestSettings.hidden,true);
 count=calls.length;accept=false;
 elements.substrateSetUpperRightButton.events.click();await settle();
 assert.equal(calls.length,count); // Substrate registration still honors its dialog.
 accept=true;
 elements.substrateTestButton.events.click();await settle();
 assert.deepEqual(calls.at(-1).body,{mode:'mock',xy_speed:2});
 assert.equal(calls.at(-1).url,'/api/substrate/run');
 console.log('Point/Line/Circle controls: selection, payload, summary, progress, busy state, input validation and substrate regression passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
