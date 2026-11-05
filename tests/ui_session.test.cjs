const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('src/airlock/static/app.js','utf8').split('function view(name)')[0];
function setup(responses){
 const calls=[];
 const context=vm.createContext({document:{},fetch:async(path,options)=>{
  calls.push({path,options});
  const next=responses.shift();if(next instanceof Error)throw next;
  assert.ok(next,'Unexpected extra request');
  return {status:next[0],ok:next[0]>=200&&next[0]<300,json:async()=>next[1]};
 }});
 vm.runInContext(source+"\nstate.csrf='old';",context);
 return {calls,run:()=>vm.runInContext("api('/api/calendar-sources','POST',{calendar_id:'test'})",context)};
}
test('a stale tab refreshes CSRF and retries a rejected calendar selection once',async()=>{
 const w=setup([[403,{code:'local_csrf_changed'}],[200,{csrf:'fresh'}],[200,{added:true}]]);
 assert.equal((await w.run()).added,true);
 assert.deepEqual(w.calls.map(c=>c.path),['/api/calendar-sources','/api/session','/api/calendar-sources']);
 assert.equal(w.calls[2].options.headers['X-Airlock-CSRF'],'fresh');
 assert.equal(w.calls[0].options.body,w.calls[2].options.body);
});
test('an expired session uses the local landing page before retrying',async()=>{
 const w=setup([[401,{code:'local_session_expired'}],[401,{}],[200,{}],[200,{csrf:'fresh'}],[200,{}]]);
 await w.run();assert.deepEqual(w.calls.map(c=>c.path),['/api/calendar-sources','/api/session','/','/api/session','/api/calendar-sources']);
});
test('origin violations and handler errors are never retried',async()=>{
 for(const status of [403,409,500]){
  const w=setup([[status,{detail:'Rejected'}]]);await assert.rejects(w.run(),/Rejected/);assert.equal(w.calls.length,1);
 }
 const w=setup([new Error('Disconnected')]);await assert.rejects(w.run(),/Disconnected/);assert.equal(w.calls.length,1);
});
test('session recovery is bounded even if the cookie changes again',async()=>{
 const w=setup([[403,{code:'local_csrf_changed'}],[200,{csrf:'fresh'}],[403,{code:'local_csrf_changed',detail:'Refresh Airlock'}]]);
 await assert.rejects(w.run(),/Refresh Airlock/);assert.equal(w.calls.length,3);
});
