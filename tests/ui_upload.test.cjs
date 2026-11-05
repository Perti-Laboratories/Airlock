const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
function ui(result={status:'ready',id:'synthetic-id',title:'example.txt',chunks:1}){
 const nodes=new Map(),requests=[],notices=[];
 function element(){return {textContent:'',files:[],children:[],hidden:true,disabled:false,clicks:0,append(...c){this.children.push(...c);},replaceChildren(){this.children=[];},click(){this.clicks++;}};}
 const $=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const state={busy:false};
 const context=vm.createContext({$,state,document:{querySelectorAll:()=>[]},el:element,button:element,banner:m=>notices.push(m),
  setBusy:value=>{state.busy=value;$('#upload-document').disabled=value;},
  FileReader:class{readAsDataURL(){this.result='data:text/plain;base64,c3ludGhldGlj';this.onload();}},
  api:async(path,method,body)=>{requests.push({path,method,body});return {result};}});
 vm.runInContext(fs.readFileSync('src/airlock/static/knowledge.js','utf8'),context);
 return {$,state,requests,notices,choose:async file=>{$('#chat-upload').files=file?[file]:[];await $('#chat-upload').onchange();}};
}
test('plus opens the file picker and selection uploads without another button',async()=>{
 const w=ui();w.$('#upload-document').onclick();assert.equal(w.$('#chat-upload').clicks,1);
 await w.choose({name:'example.txt',size:40});assert.equal(w.requests.length,1);assert.equal(w.requests[0].path,'/api/knowledge/upload');
 assert.equal(w.requests[0].body.filename,'example.txt');assert.equal(w.$('#chat-attachments').hidden,false);assert.equal(w.$('#chat-attachments').children.length,1);
 assert.equal(w.state.busy,false);assert.equal(w.$('#chat-upload').value,'');
});
test('canceling the picker never uploads',async()=>{const w=ui();await w.choose(null);assert.equal(w.requests.length,0);});
test('oversized attachment stays out of the upload request',async()=>{const w=ui();await w.choose({name:'large.txt',size:3*1024*1024});assert.equal(w.requests.length,0);assert.match(w.notices[0],/2 MB/);});
test('failed indexing stays visible and does not attach an unusable source',async()=>{
 const w=ui({status:'failed'});await w.choose({name:'example.txt',size:40});assert.equal(w.$('#chat-attachments').children.length,0);
 assert.match(w.$('#upload-status').textContent,/Settings & Activity/);assert.equal(w.$('#upload-status').hidden,false);assert.equal(w.state.busy,false);
});
