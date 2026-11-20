const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {document,nodes}=require('./ui_dom_helper.cjs');const ctx=vm.createContext({document,URL});
vm.runInContext(fs.readFileSync('src/airlock/static/markdown.js','utf8'),ctx);
const render=text=>vm.runInContext(`ChatMarkdown.render(${JSON.stringify(text)})`,ctx);
test('chat formats bold emphasis lists headings and code without HTML parsing',()=>{
 const root=render('# Overview\n\n**Bold** and *italic* with `literal **code**`\n\n- First\n- Second\n\n1. Ordered\n2. Next\n\n```js\n<script>literal</script>\n```');
 assert.equal(nodes(root,'strong')[0].textContent,'Bold');assert.equal(nodes(root,'em')[0].textContent,'italic');
 assert.equal(nodes(root,'li').length,4);assert.equal(nodes(root,'h2').length,1);
 assert.equal(nodes(root,'pre')[0].textContent,'<script>literal</script>');assert.equal(nodes(root,'script').length,0);
});
test('model text cannot add active HTML images trackers or unsafe links',()=>{
 const root=render('<img src="https://tracker.invalid" onerror="alert(1)">\n![tracking](https://tracker.invalid/pixel)\n[x](javascript:alert) [y](data:text/html,test) [safe](https://example.test/path)');
 assert.equal(nodes(root,'img').length,0);assert.equal(nodes(root,'script').length,0);assert.equal(nodes(root,'a').length,1);
 const a=nodes(root,'a')[0];assert.equal(a.href,'https://example.test/path');assert.equal(a.rel,'noopener noreferrer');assert.equal(a.referrerPolicy,'no-referrer');
 assert.match(root.textContent,/<img src=/);
});
test('escaped markers, unfinished fences and long text remain inert',()=>{
 assert.equal(nodes(render('\\*\\*literal\\*\\*'),'strong').length,0);
 assert.equal(nodes(render('```\n**literal**'),'strong').length,0);
 assert.ok(render('a'.repeat(20000)).textContent.length===20000);
});
