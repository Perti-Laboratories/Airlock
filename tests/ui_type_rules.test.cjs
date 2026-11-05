const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(){
 const nodes=new Map(),calls=[];
 const make=(tag='',cls='',text='')=>({tag,className:cls,textContent:text,dataset:{},children:[],handlers:{},checked:false,hidden:false,disabled:false,value:'',
  append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
  addEventListener(event,fn){this.handlers[event]=fn;},setAttribute(){}});
 const $=id=>{if(!nodes.has(id))nodes.set(id,make());return nodes.get(id);};
 const descendants=node=>[node,...node.children.flatMap(descendants)];
 const document={createTextNode:text=>make('text','',text),
  querySelector(selector){const [,attr,key]=selector.match(/\[data-(release-type|type-level)="([^"]+)"\]/);
   return descendants($('#release-type-rules')).find(n=>n.dataset[attr==='release-type'?'releaseType':'typeLevel']===key);},
  querySelectorAll(selector){return selector==='#release-source-rules select'?descendants($('#release-source-rules')).filter(n=>n.tag==='select'):[];}};
 const context=vm.createContext({$,document,el:make,api:async(...args)=>{calls.push(args);return {};},refreshSharing:async()=>{},setInterval(){},clearInterval(){}});
 vm.runInContext(fs.readFileSync('src/airlock/static/controls.js','utf8'),context);
 const values={calendar:'busy',todo:'private',contacts:'private',memory:'private',company_memory:'private'};
 vm.runInContext('releaseState.policy={revision:8};renderTypeRules('+JSON.stringify(values)+')',context);
 const source=make('select');source.dataset.source='local';source.value='original';$('#release-source-rules').append(source);
 return {$,calls,context,values,document,run:code=>vm.runInContext(code,context)};
}
test('type switches keep unsupported types private and disable levels when off',()=>{
 const w=setup();
 assert.equal(w.document.querySelector('[data-release-type="contacts"]').disabled,true);
 assert.equal(w.document.querySelector('[data-release-type="contacts"]').checked,false);
 assert.equal(w.document.querySelector('[data-type-level="todo"]').disabled,true);
 const toggle=w.document.querySelector('[data-release-type="todo"]');toggle.checked=true;toggle.handlers.change();
 assert.equal(w.document.querySelector('[data-type-level="todo"]').disabled,false);
 assert.equal(w.run('draftTypeRules().todo'),'title');
 toggle.checked=false;toggle.handlers.change();assert.equal(w.run('draftTypeRules().todo'),'private');
});
test('saving submits type ceilings and source restrictions together',async()=>{
 const w=setup();w.$('#release-paused').checked=false;
 await w.$('#release-policy-form').handlers.submit({preventDefault(){}});
 const [path,method,body]=w.calls[0];assert.equal(path,'/api/release-policy');assert.equal(method,'PUT');
 assert.deepEqual(JSON.parse(JSON.stringify(body.type_rules)),w.values);
 assert.deepEqual(JSON.parse(JSON.stringify(body.rules)),{local:'original'});
 assert.equal(body.expected_revision,8);
});
test('original title acknowledgement appears only when calendar ceiling permits it',()=>{
 const w=setup();w.run('releaseState.dirty=true;updateReleaseDraft()');
 assert.equal(w.$('#release-title-confirmation').hidden,true);
 w.document.querySelector('[data-type-level="calendar"]').value='original';w.run('updateReleaseDraft()');
 assert.equal(w.$('#release-title-confirmation').hidden,false);
 w.document.querySelector('[data-release-type="calendar"]').checked=false;w.run('updateReleaseDraft()');
 assert.equal(w.$('#release-title-confirmation').hidden,true);
});
