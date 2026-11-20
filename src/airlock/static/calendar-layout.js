'use strict';
// Pure civil-date layout helpers. Provider instants stay untouched; the selected zone controls display.
const CalendarLayout = (() => {
  const key = (value, zone) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
    return `${p.year}-${p.month}-${p.day}`;
  };
  const addDays = (day,n) => new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
  const weekStart = day => addDays(day,-new Date(day+'T12:00:00Z').getUTCDay());
  function days(anchor,view) {
    let first=anchor,count=1;
    if(view==='week'){first=weekStart(anchor);count=7;}
    if(view==='month'){first=weekStart(anchor.slice(0,7)+'-01');count=42;}
    return Array.from({length:count},(_,i)=>addDays(first,i));
  }
  function onDay(event,day,zone) {
    if(event.all_day)return event.start<=day&&day<event.end;
    const start=Date.parse(event.start),end=Date.parse(event.end);
    if(start===end)return key(start,zone)===day;
    return key(start,zone)<=day&&day<=key(end-1,zone);
  }
  function minutes(value,zone) {
    const p=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:zone,hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
    return Number(p.hour)*60+Number(p.minute)+Number(p.second)/60;
  }
  function segment(event,day,zone) {
    if(event.all_day||!onDay(event,day,zone))return null;
    const a=Date.parse(event.start),b=Date.parse(event.end),point=a===b;
    const start=key(a,zone)<day?0:minutes(a,zone);
    const end=point?start:key(b,zone)>day?1440:minutes(b,zone);
    // Repeated-hour events retain explicit offset times in details; never create a negative box.
    return {event,start,end:Math.max(start,end),point};
  }
  function lanes(segments) {
    const rows=segments.slice().sort((a,b)=>a.start-b.start||b.end-a.end);
    let group=[],until=-1;
    const finish=()=>{let ends=[];for(const row of group){let lane=ends.findIndex(end=>end<=row.start);if(lane<0)lane=ends.length;ends[lane]=Math.max(row.end,row.start+12);row.lane=lane;}for(const row of group)row.lanes=ends.length;group=[];};
    for(const row of rows){if(row.start>=until){finish();until=-1;}group.push(row);until=Math.max(until,row.end,row.start+12);}finish();return rows;
  }
  function source(event,sources=[]) {
    if(event.source==='connector')return event.origin==='recipient'?{key:'incoming',label:'Incoming · connected planner',color:'#8056a4'}:{key:'availability',label:'External',color:'#c53030'};
    if(event.source==='google'){
      const id=event.source_id||'google';let hash=0;for(const ch of id)hash=(hash*31+ch.charCodeAt(0))>>>0;
      const palette=['#2563a6','#a85025','#287b85','#a0376b','#6b65ad','#7c7026'];
      return {key:id,label:'Google · '+(sources.find(s=>s.id===id)?.name||'Calendar'),color:palette[hash%palette.length]};
    }
    return {key:'local',label:'Local workspace',color:'#367052'};
  }
  return {key,addDays,weekStart,days,onDay,minutes,segment,lanes,source};
})();
if(typeof module!=='undefined')module.exports=CalendarLayout;
