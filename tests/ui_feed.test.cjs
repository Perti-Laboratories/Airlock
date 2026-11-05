const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
function setup(){
 const source=fs.readFileSync('src/airlock/static/app.js','utf8');const nodes=new Map(),requests=[],renders=[];
 const $=id=>{if(!nodes.has(id))nodes.set(id,{scrollHeight:100,scrollTop:0,clientHeight:100,hidden:false});return nodes.get(id);};
 const state={busy:false};let respond=async()=>({items:[],next:null});
 const context=vm.createContext({$,state,URLSearchParams,Map,JSON,encodeURIComponent,
  renderMessages:items=>renders.push(items),api:async(...args)=>{requests.push(args);return respond(...args);}});
 vm.runInContext(source.slice(source.indexOf('const feedState ='),source.indexOf('function renderMessages')),context);
 return {state,requests,renders,$,run:code=>vm.runInContext(code,context),respond:fn=>{respond=fn;}};
}
const item={key:'message:1',id:'1',role:'assistant',content:'Synthetic response',metadata:{}};
test('unchanged polling does not redraw the feed or disturb reading',async()=>{
 const w=setup();w.respond(async()=>({items:[item],next:null}));
 await w.run('refreshFeed()');await w.run('refreshFeed()');assert.equal(w.renders.length,1);
 assert.equal(w.$('#feed-acknowledge-all').hidden,false);
});
test('a pending refresh cannot overwrite an in-progress outgoing message',async()=>{
 const w=setup();let finish;w.respond(()=>new Promise(r=>finish=r));
 const pending=w.run('refreshFeed()');w.state.busy=true;finish({items:[item],next:null});await pending;
 assert.equal(w.renders.length,0);
});
test('a later history request wins over a slower active-feed response',async()=>{
 const w=setup();let finish;w.respond(()=>new Promise(r=>finish=r));const pending=w.run('refreshFeed()');
 w.run('feedState.history=true');w.respond(async()=>({items:[],next:null}));await w.run('refreshFeed()');
 finish({items:[item],next:null});await pending;assert.equal(w.renders.length,1);assert.equal(w.renders[0].length,0);
 assert.match(w.requests[1][0],/acknowledged=true/);
});
test('acknowledgement waits for persistence before updating the feed',async()=>{
 const w=setup();let persist;w.respond((path,method)=>method==='POST'?new Promise(r=>persist=r):Promise.resolve({items:[],next:null}));
 const pending=w.run(`acknowledgeItem(${JSON.stringify(item)})`);assert.equal(w.requests.length,1);assert.equal(w.renders.length,0);
 assert.equal(w.requests[0][0],'/api/feed/message%3A1/acknowledge');persist({});await pending;assert.equal(w.renders.length,1);
});
test('older pages use server cursors and keep the latest loaded records',async()=>{
 const w=setup();w.respond(async()=>({items:[item],next:{before:'2026-10-27T10:00:00+00:00',before_key:'message:1'}}));await w.run('refreshFeed()');
 w.respond(async()=>({items:[{...item,key:'message:0'}],next:null}));await w.run('refreshFeed(true)');
 assert.match(w.requests[1][0],/before_key=message%3A1/);assert.equal(w.renders.at(-1).length,2);assert.equal(w.$('#feed-latest').hidden,false);
});
