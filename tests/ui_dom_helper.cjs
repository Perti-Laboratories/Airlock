class Node{
 constructor(tag,text=''){this.tagName=tag;this.children=[];this.value='';this.checked=false;this.hidden=false;this.attrs={};this.style={setProperty(){}};this.classList={add(){},remove(){},toggle(){}};this._text=text;this.listeners={};}
 append(...nodes){this.children.push(...nodes.map(n=>typeof n==='string'?new Node('#text',n):n));}
 replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
 get childNodes(){return this.children;}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
 set textContent(v){this._text=String(v);this.children=[];}
 setAttribute(k,v){this.attrs[k]=String(v);}
 addEventListener(k,v){this.listeners[k]=v;}
 get innerHTML(){throw Error('HTML parsing is forbidden in this test');}
 set innerHTML(v){throw Error('HTML parsing is forbidden in this test');}
}
const document={createElement:tag=>new Node(tag),createTextNode:text=>new Node('#text',text)};
function nodes(root,tag){return [root,...root.children.flatMap(n=>nodes(n))].filter(n=>!tag||n.tagName===tag);}
module.exports={Node,document,nodes};
