const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const ids = ['readyXY','readyZ','readyXYZ','readyX','readyY','readyPositionZ',
 'readySave','readyCapture','readySavedText','readyStatus'];
const elements = Object.fromEntries(ids.map(id => [id, {value:'',disabled:false,textContent:'',events:{},
 addEventListener(event, fn){this.events[event] = fn;}}]));
const saved = {schema:1,frame:'esp300-home-mm',position:{x:-19.125,y:6.25,z:17.375}};
let state = {connected:true,dryRun:false,run:{running:false},ready:{saved,error:null,run:null},manualMotion:{active:false}};
const calls = [], runs = [];
let reject = false;
const context = {document:{getElementById:id=>elements[id]}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/visualizer/ready-controls.js','utf8')
 .replace('export function createReadyControls', 'function createReadyControls'), context);
let controls;
controls = context.createReadyControls({document:context.document,
 request: async(url, options) => {
  const body = JSON.parse(options.body); calls.push({url,body});
  if (reject) throw new Error('Injected refusal');
  if (url.endsWith('/move')) return {running:true,readyAxes:body.axes};
  state = {...state,ready:{saved:{...saved,position:body.position || {x:1,y:2,z:3}},error:null,run:null}};
  return state;
 }, onStatus:data=>controls.update(data),onRun:data=>runs.push(data),refresh:async()=>{}});

async function main(){
 controls.update(state);
 assert.equal(elements.readyX.value,'-19.125');
 assert.match(elements.readySavedText.textContent,/17\.37500/);
 for(const [id, axes] of [['readyXY','xy'],['readyZ','z'],['readyXYZ','xyz']]){
  controls.update(state);
  await elements[id].events.click();
  assert.deepEqual(calls.at(-1),{url:'/api/jog/ready/move',body:{mode:'live',axes}});
  assert.equal(elements.readyXY.disabled,true);
  assert.equal(elements.readyZ.disabled,true);
  assert.equal(runs.at(-1).readyAxes,axes);
 }
 controls.update(state);
 elements.readyX.value='-40';elements.readyX.events.input();
 assert.equal(elements.readyXY.disabled,true);
 controls.update(state); // Polling must preserve a pending edit.
 assert.equal(elements.readyX.value,'-40');
 await elements.readySave.events.click();
 assert.equal(calls.at(-1).body.position.x,-40);
 assert.equal(elements.readyXY.disabled,false);
 const before=calls.length;
 elements.readyY.value='';elements.readyY.events.input();
 await elements.readySave.events.click();
 assert.equal(calls.length,before);
 assert.match(elements.readyStatus.textContent,/모두 입력/);
 elements.readyY.value='15';elements.readyY.events.input();
 reject=true;await elements.readySave.events.click();reject=false;
 assert.match(elements.readyStatus.textContent,/Injected refusal/);
 assert.equal(elements.readyXY.disabled,true);
 await elements.readyCapture.events.click();
 assert.deepEqual(calls.at(-1),{url:'/api/jog/ready/capture',body:{mode:'live'}});
 assert.equal(elements.readyX.value,'1');
 controls.update({...state,dryRun:true});
 assert.equal(elements.readyCapture.disabled,true);
 await elements.readyZ.events.click();
 assert.deepEqual(calls.at(-1).body,{mode:'mock',axes:'z'});
 for(const busy of [{connected:false},{run:{running:true}},{manualMotion:{active:true}},
                    {sensorHome:{running:true}},{connectionPreparation:{active:true}}]){
  controls.update({...state,...busy});
  assert.equal(elements.readyXY.disabled,true);
  assert.equal(elements.readyZ.disabled,true);
  assert.equal(elements.readyXYZ.disabled,true);
 }
 const html=fs.readFileSync(__dirname+'/visualizer/index.html','utf8');
 assert.match(html,/<legend>Ready<\/legend>/);
 for(const [id,label] of [['readyXY','XY'],['readyZ','Z'],['readyXYZ','XYZ']]){
  assert.match(html,new RegExp('id="'+id+'"[^>]*>'+label+'<\\/button>'));
 }
 console.log('Ready UI: masks, modes, busy states, persistence, edit protection and labels passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
