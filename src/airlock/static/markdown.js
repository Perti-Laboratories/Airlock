'use strict';
// Deliberately small Markdown renderer: text nodes only; no raw HTML, images or embedded media.
const ChatMarkdown=(()=>{
 function inline(parent,text,depth=0){
  if(depth>8){parent.append(document.createTextNode(text));return;}
  const tokens=/\\([\\`*_\[\]{}()#+\-.!>])|`([^`\n]+)`|!\[([^\]\n]*)\]\(([^)\n]*)\)|\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^\n]+?)\*\*|__([^\n]+?)__|\*([^*\n]+)\*|_([^_\n]+)_/g;
  let last=0,m;
  while((m=tokens.exec(text))){
   parent.append(document.createTextNode(text.slice(last,m.index)));last=tokens.lastIndex;
   if(m[1]){parent.append(document.createTextNode(m[1]));continue;}
   if(m[2]){const n=document.createElement('code');n.textContent=m[2];parent.append(n);continue;}
   if(m[3]!==undefined){parent.append(document.createTextNode(m[3]?'[Image: '+m[3]+']':'[Image]'));continue;}
   if(m[5]){
    let url;try{url=new URL(m[6]);}catch{}
    if(url&&['http:','https:','mailto:'].includes(url.protocol)&&!url.username&&!url.password){
     const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';inline(a,m[5],depth+1);parent.append(a);
    }else parent.append(document.createTextNode(m[5]));
    continue;
   }
   const n=document.createElement(m[7]||m[8]?'strong':'em');inline(n,m[7]||m[8]||m[9]||m[10],depth+1);parent.append(n);
  }
  parent.append(document.createTextNode(text.slice(last)));
 }
 function render(text){
  const root=document.createElement('div');root.className='message-text markdown';
  const lines=String(text??'').replace(/\r\n?/g,'\n').split('\n');let i=0;
  const special=line=>/^(?:\s*```|#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|>\s?)/.test(line);
  while(i<lines.length){
   const line=lines[i];if(!line.trim()){i++;continue;}
   if(/^\s*```/.test(line)){const content=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i]))content.push(lines[i++]);if(i<lines.length)i++;const pre=document.createElement('pre'),code=document.createElement('code');code.textContent=content.join('\n');pre.append(code);root.append(pre);continue;}
   const heading=/^(#{1,6})\s+(.+)$/.exec(line);
   if(heading){const n=document.createElement('h'+Math.min(heading[1].length+1,6));inline(n,heading[2]);root.append(n);i++;continue;}
   const list=/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/.exec(line);
   if(list){const n=document.createElement(list[1]?'ul':'ol');if(list[2])n.start=Number(list[2]);while(i<lines.length){const item=/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/.exec(lines[i]);if(!item||!!item[1]!==!!list[1])break;const li=document.createElement('li');inline(li,item[3]);n.append(li);i++;}root.append(n);continue;}
   if(/^>\s?/.test(line)){const n=document.createElement('blockquote');while(i<lines.length&&/^>\s?/.test(lines[i])){if(n.childNodes.length)n.append(document.createElement('br'));inline(n,lines[i++].replace(/^>\s?/,''));}root.append(n);continue;}
   const p=document.createElement('p');inline(p,line);i++;while(i<lines.length&&lines[i].trim()&&!special(lines[i])){p.append(document.createElement('br'));inline(p,lines[i++]);}root.append(p);
  }
  return root;
 }
 return {render};
})();
if(typeof module!=='undefined')module.exports=ChatMarkdown;
