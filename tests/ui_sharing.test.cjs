// Exercise authority-relevant UI transitions without touching a real connection.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function workspace(overrides={}){
 const nodes=new Map(),calls=[],refreshes=[];
 const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',checked:false,disabled:false,hidden:false,classList:{toggle(){}},addEventListener(){}});return nodes.get(id);};
 const saved={revision:7,paused:true,rules:{local:'busy',calendar:'original'},type_rules:{calendar:'busy',todo:'private',contacts:'private',memory:'private',company_memory:'private'}};
 const connection={paired:true,enabled:true,allow_availability:false,release_paused:true,...overrides};
 const context=vm.createContext({$:node,releaseState:{policy:saved,dirty:false},setInterval(){},document:{},
  refreshReleases:async options=>refreshes.push(options),
  api:async(path,method,body)=>{
   if(method){calls.push({path,method,body});if(path==='/api/release-policy')connection.release_paused=body.paused;if(path==='/api/exchange')Object.assign(connection,body);return {};}
   return {...connection};
  },banner(){},view(){},el(){},button(){}});
 vm.runInContext(fs.readFileSync('src/airlock/static/exchange.js','utf8'),context);
 vm.runInContext('sharingState.connection='+JSON.stringify(connection),context);
 return {nodes,node,calls,refreshes,context,saved,connection,click:()=>node('#sharing-toggle').onclick()};
}
test('resume changes only saved policy, preserves title authorization and never broadens connection permissions',async()=>{
 const w=workspace();await w.click();assert.equal(w.calls.length,1);
 assert.deepEqual(JSON.parse(JSON.stringify(w.calls[0])),{path:'/api/release-policy',method:'PUT',body:{expected_revision:7,paused:false,rules:w.saved.rules,type_rules:w.saved.type_rules,acknowledge_titles:true}});
 assert.equal(w.node('#sharing-toggle').textContent,'Pause sharing');
});
test('unsaved rules cannot be released through Resume',async()=>{
 const w=workspace();w.context.releaseState.dirty=true;vm.runInContext('renderSharingStatus()',w.context);
 assert.equal(w.node('#sharing-toggle').disabled,true);await w.click();assert.equal(w.calls.length,0);
});
test('Pause remains available with unsaved edits and preserves the draft',async()=>{
 const w=workspace({release_paused:false});w.context.releaseState.dirty=true;
 await w.click();assert.equal(w.calls[0].body.paused,true);assert.equal(w.refreshes[0].preserveDraft,true);
});
test('enabling a connection does not unpause outbound sharing or enable incoming data',async()=>{
 const w=workspace({enabled:false});await w.click();assert.equal(w.calls.length,1);
 assert.equal(w.calls[0].path,'/api/exchange');assert.equal(w.calls[0].body.allow_availability,false);
 assert.equal(w.connection.release_paused,true);assert.equal(w.node('#sharing-toggle').textContent,'Resume sharing');
});
test('unpaired workspaces cannot dispatch connection or release writes',async()=>{
 const w=workspace({paired:false,enabled:false});await w.click();assert.equal(w.calls.length,0);
});
test('stale-policy rejection is shown without claiming sharing resumed',async()=>{
 const w=workspace();w.context.api=async()=>{throw Error('Rules changed. Refresh first.');};await w.click();
 assert.equal(w.node('#sharing-result').textContent,'Rules changed. Refresh first.');
 assert.equal(w.node('#sharing-toggle').textContent,'Resume sharing');
});
