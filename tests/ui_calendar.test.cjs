const test=require('node:test'),assert=require('node:assert/strict');
const cal=require('../src/airlock/static/calendar-layout.js');
const event=(start,end,extra={})=>({start,end,source:'local',all_day:false,...extra});
test('week and month civil dates cross month/year boundaries',()=>{
 assert.deepEqual(cal.days('2027-01-01','week'),['2026-12-27','2026-12-28','2026-12-29','2026-12-30','2026-12-31','2027-01-01','2027-01-02']);
 assert.equal(cal.days('2026-11-17','month').length,42);assert.deepEqual(cal.days('2026-11-17','day'),['2026-11-17']);
});
test('exclusive ends, cross-midnight events and zero-duration markers use selected zone',()=>{
 const midnight=event('2026-11-17T23:00:00-05:00','2026-11-18T00:00:00-05:00');
 assert.equal(cal.onDay(midnight,'2026-11-18','America/New_York'),false);
 assert.equal(cal.segment(midnight,'2026-11-17','America/New_York').end,1440);
 const point=event('2026-11-18T00:00:00-05:00','2026-11-18T00:00:00-05:00');
 assert.equal(cal.onDay(point,'2026-11-18','America/New_York'),true);assert.equal(cal.segment(point,'2026-11-18','America/New_York').point,true);
 const overnight=event('2026-11-17T23:00:00-05:00','2026-11-18T01:00:00-05:00');
 assert.equal(cal.segment(overnight,'2026-11-18','America/New_York').start,0);
 assert.equal(cal.segment(overnight,'2026-11-18','America/New_York').end,60);
 assert.equal(cal.onDay(event('2026-11-17','2026-11-18',{all_day:true}),'2026-11-18','UTC'),false);
});
test('layout preserves short durations and handles DST without negative boxes',()=>{
 const short=cal.segment(event('2026-11-17T11:00:00-05:00','2026-11-17T11:30:00-05:00'),'2026-11-17','America/New_York');assert.equal(short.end-short.start,30);
 const fold=cal.segment(event('2026-11-01T01:45:00-04:00','2026-11-01T01:15:00-05:00'),'2026-11-01','America/New_York');assert.ok(fold.end>=fold.start);
 assert.equal(cal.key('2026-11-18T01:00:00Z','America/Los_Angeles'),'2026-11-17');
});
test('overlapping events use separate lanes while adjacent events reuse lanes',()=>{
 const rows=cal.lanes([{start:600,end:630},{start:615,end:660},{start:660,end:690}]);
 assert.notEqual(rows[0].lane,rows[1].lane);assert.equal(rows[0].lanes,2);assert.equal(rows[2].lanes,1);
});
test('source colors are stable across reorder and labels distinguish both incoming classes',()=>{
 const a={source:'google',source_id:'source-one'},s=[{id:'source-one',name:'Work'},{id:'two',name:'Other'}];
 assert.deepEqual(cal.source(a,s),cal.source(a,s.slice().reverse()));
 assert.notEqual(cal.source({source:'connector',origin:'recipient'}).key,cal.source({source:'connector',origin:'availability'}).key);
 assert.notEqual(cal.source(a,s).color,cal.source({source:'connector',origin:'recipient'}).color);
});
test('generic external availability is red and distinct from connected domain records',()=>{
 assert.deepEqual(cal.source({source:'connector',origin:'availability'}),{key:'availability',label:'External',color:'#c53030'});
 assert.notEqual(cal.source({source:'connector',origin:'recipient'}).color,'#c53030');
});
