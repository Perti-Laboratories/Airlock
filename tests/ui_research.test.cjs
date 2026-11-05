const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
function setup(){
 const nodes=new Map(),timers=new Map(),requests=[];let id=0;let respond=async()=>({steps:[],status:'running'});
 function el(tag,cls,text){return {tag,className:cls,textContent:text,children:[],hidden:true,attrs:{},scrollHeight:100,
 append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},setAttribute(k,v){this.attrs[k]=v;}};}
 const $=key=>{if(!nodes.has(key))nodes.set(key,el('div'));return nodes.get(key);};
 const context=vm.createContext({$,el,setInterval:f=>{timers.set(++id,f);return id;},clearInterval:i=>timers.delete(i),
 api:async path=>{requests.push(path);return respond();}});
 vm.runInContext(fs.readFileSync('src/airlock/static/research.js','utf8'),context);
 return {$,requests,run:s=>vm.runInContext(s,context),timers,respond:f=>respond=f,poll:()=>[...timers.values()][0]()};
}
test('research progress shows real stage details and stops with the response',async()=>{
 const w=setup();w.run("startChatProgress('turn-one')");assert.equal(w.$('#chat-progress').hidden,false);
 w.respond(async()=>({status:'running',steps:[{key:'company_search_1',label:'Search company memory 1/2',status:'running',detail:'Project Cedar dates deadlines timeline'}]}));
 await w.poll();const row=w.$('#chat-progress').children[0].children[0];
 assert.match(row.children[0].textContent,/Search company memory/);assert.match(row.children[1].textContent,/Project Cedar/);
 assert.equal(w.requests[0],'/api/chat-progress/turn-one');w.run('stopChatProgress()');assert.equal(w.timers.size,0);assert.equal(w.$('#chat-progress').hidden,true);
});
test('polls do not overlap and an old turn cannot overwrite the next turn',async()=>{
 const w=setup();let resolve;w.respond(()=>new Promise(r=>resolve=r));w.run("startChatProgress('old')");
 const pending=w.poll();await w.poll();assert.equal(w.requests.length,1);
 w.run("startChatProgress('new')");resolve({steps:[{label:'OLD RESULT',status:'completed'}]});await pending;
 assert.equal(w.$('#chat-progress').children[0].textContent,'Starting local research…');assert.equal(w.timers.size,1);
});
test('progress errors preserve the request and can recover on the next poll',async()=>{
 const w=setup();w.run("startChatProgress('turn')");w.respond(async()=>{throw new Error('Not ready');});await w.poll();
 assert.equal(w.$('#chat-progress').hidden,false);assert.equal(w.timers.size,1);
 w.respond(async()=>({steps:[{label:'Think locally',status:'completed'}]}));await w.poll();
 assert.match(w.$('#chat-progress').children[0].children[0].children[0].textContent,/Think locally/);
});

test('unchanged progress is not redrawn or repeatedly announced',async()=>{
 const w=setup();w.run("startChatProgress('turn')");w.respond(async()=>({steps:[{label:'Think locally',status:'running'}]}));
 await w.poll();const first=w.$('#chat-progress').children[0];await w.poll();assert.equal(w.$('#chat-progress').children[0],first);
});
