// Hardware-free DOM contract test for the Select Test controls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = {};
for (const id of ['substrateTestButton','substrateSetUpperRightButton','substrateGoUpperRightButton',
 'substrateStatusText','substrateReferenceText','testSelect','pointTestSettings','pointDepth',
 'pointIngressSpeed','jogDryRun','travelRate']) {
 elements[id] = {value:'',hidden:false,disabled:false,textContent:'',events:{},
  addEventListener(event,callback){this.events[event]=callback;}};
}
Object.assign(elements.testSelect,{value:'substrate'});
Object.assign(elements.pointDepth,{value:'3'});
Object.assign(elements.pointIngressSpeed,{value:'0.01'});
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
  {mode:'mock',depth_mm:3,ingress_speed:0.01});
 assert.equal(confirmations.length,0); // Point starts immediately, without a dialog.
 assert.equal(elements.testSelect.disabled,true);
 // Trigger the stored polling callback in a fresh VM to verify total=2 and unlock.
 let poll;
 const second={...context,setInterval:callback=>{poll=callback;}};
 vm.runInNewContext(fs.readFileSync(__dirname+'/visualizer/substrate-dialog.js','utf8'),second);
 await settle();
 elements.pointDepth.value='2';elements.pointIngressSpeed.value='0.2';
 elements.substrateTestButton.events.click();await settle();
 state={status:'completed',completed:2,total:2,phase:'completed'};
 await poll();
 assert.match(elements.substrateStatusText.textContent,/2\/2/);
 assert.equal(elements.testSelect.disabled,false);
 let count=calls.length;
 elements.pointIngressSpeed.value='0.001';
 elements.substrateTestButton.events.click();await settle();
 assert.equal(calls.length,count);
 assert.match(elements.substrateStatusText.textContent,/0.01/);
 elements.pointIngressSpeed.value='0.01';
 elements.testSelect.value='substrate';elements.testSelect.events.change();await settle();
 assert.equal(elements.substrateSetUpperRightButton.hidden,false);
 assert.equal(elements.pointTestSettings.hidden,true);
 count=calls.length;accept=false;
 elements.substrateSetUpperRightButton.events.click();await settle();
 assert.equal(calls.length,count); // Substrate registration still honors its dialog.
 accept=true;
 elements.substrateTestButton.events.click();await settle();
 assert.deepEqual(calls.at(-1).body,{mode:'mock',xy_speed:2});
 assert.equal(calls.at(-1).url,'/api/substrate/run');
 console.log('Point controls: immediate start without registration/dialog, defaults, payload, progress, validation and substrate regression passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
