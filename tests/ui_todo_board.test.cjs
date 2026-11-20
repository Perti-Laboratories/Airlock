const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {Node,document,nodes}=require('./ui_dom_helper.cjs');
function setup(){const elements=new Map();const $=id=>{if(!elements.has(id))elements.set(id,new Node('div'));return elements.get(id);};
 const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;};
 let response=async()=>[];const context=vm.createContext({document,$,el,button:(text,fn,cls)=>el('button',cls,text),api:()=>response(),banner:()=>{},Date,Map});
 const source=fs.readFileSync('src/airlock/static/exchange.js','utf8');vm.runInContext(source.slice(source.indexOf('const todoColumns='),source.indexOf('function editTodo')),context);
 return {$,run:c=>vm.runInContext(c,context),respond:r=>response=r};}
const incoming={id:'return-1',title:'Connected task',read_only:true,status:'open',board_column:'backlog',board_editable:true,revision:1};
test('returned tasks render alongside local tasks and expose hidden finished count',async()=>{
 const w=setup();w.respond(async()=>[incoming,{id:'local',title:'Local task',status:'open'}, {...incoming,id:'done',title:'Finished connected task',status:'done',board_column:'done'}]);await w.run('refreshTodos()');
 assert.match(w.$('#todo-list').textContent,/Connected task/);assert.match(w.$('#todo-list').textContent,/Local task/);
 assert.doesNotMatch(w.$('#todo-list').textContent,/Finished connected task/);assert.match(w.$('#todo-summary').textContent,/1 finished hidden/);
 w.$('#todo-show-finished').checked=true;await w.run('refreshTodos()');assert.match(w.$('#todo-list').textContent,/Finished connected task/);
});
test('unexpected columns never silently drop a returned task',async()=>{
 const w=setup();w.respond(async()=>[{...incoming,board_column:'unknown'}]);await w.run('refreshTodos()');assert.match(w.$('#todo-list').textContent,/Connected task/);
});
test('older task polling cannot overwrite a newer board view',async()=>{
 const w=setup();let complete;w.respond(()=>new Promise(r=>complete=r));const old=w.run('refreshTodos()');
 w.respond(async()=>[incoming]);await w.run('refreshTodos()');complete([]);await old;assert.match(w.$('#todo-list').textContent,/Connected task/);
});
