// Execute shipped bundle functions in a VM, never the server or a database.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const layouts = [
  {anchor:'function t8e(t){', start:'function Omr(', end:'function $x(', load:'Umr', build:'r8e', truncate:'NZe', limit:'qx', logger:'C'},
  {anchor:'function W8e(t){', start:'function bpr(', end:'function rS(', load:'gpr', build:'y8e', truncate:'CZe', limit:'tS', logger:'C'},
  {anchor:'function Frt(t,e,r={}){', start:'function C_(', end:'var Z$=', load:'IWr', build:'Frt', logger:'X', modern:true},
];
assert.equal(layouts.reduce((n,l)=>n+source.split(l.anchor).length-1,0),1,'unknown/ambiguous history layout');
const layout = layouts.find(l=>source.includes(l.anchor));
function region(text) {
  const start=text.indexOf(layout.start), end=text.indexOf(layout.end,start);
  assert(start>=0 && end>start,'history function boundaries changed');
  return text.slice(start,end);
}
function setup(text) {
  const warnings=[];
  const context={ [layout.logger]:{warn:(...a)=>warnings.push(a),info:()=>{}}, fe:f=>f };
  if (!layout.modern) Object.assign(context,{[layout.truncate]:x=>x,[layout.limit]:0});
  vm.createContext(context);
  vm.runInContext(region(text),context);
  if(layout.modern) {
    const start=text.indexOf('function A0e('),end=text.indexOf('function Jgr(',start);
    assert(start>=0 && end>start);
    vm.runInContext('var k0e;'+text.slice(start,end)+';Wfe()',context);
  }
  return {context,warnings,load:context[layout.load],build:context[layout.build]};
}
const patched=setup(source), {context,warnings,load,build}=patched;
assert.equal(typeof load,'function'); assert.equal(typeof build,'function');
// Reconstruct ONLY the two original warning sites. Differential assertions below
// prove all output fields/descriptors/filtering remain upstream-identical.
const original=source.replace(/ekkoWarnEmptyHistory\(e,n,(?:i,X|void 0,C)\)/,
  `${layout.logger}.warn("[chat-run-socket] skipped empty assistant message %s while loading session %s",n.id,e)`)
  .replace(/ekkoWarnEmptyHistory\(t,o,void 0,[XC]\)/,
  `${layout.logger}.warn("[chat-run-socket] skipped empty assistant message while building history for session %s",t)`);
assert.notEqual(original,source,'patch calls missing');
const baseline=setup(original);
const plain=x=>JSON.parse(JSON.stringify(x));
function unchanged(rows,session='fixture',options={}) {
  const before=JSON.stringify(rows);
  for(const kind of ['load','build']) {
    const args=kind==='load'?[rows,session]:[session,rows,options];
    const actual=patched[kind](...args), expected=baseline[kind](...args);
    assert.deepEqual(plain(actual),plain(expected),`${kind}: upstream output changed`);
    assert.deepEqual(actual.map(x=>Object.getOwnPropertyDescriptor(x,'cursorId')),
      expected.map(x=>Object.getOwnPropertyDescriptor(x,'cursorId')));
  }
  assert.equal(JSON.stringify(rows),before,'input mutated');
}
const reasoning=[
  {id:1,role:'assistant',content:'',reasoning:'private reasoning'},
  {id:2,role:'assistant',content:' ',reasoning_content:'private reasoning'},
  {id:3,role:'assistant',content:'',reasoning_details:[{type:'reasoning',text:'private'}]},
  {id:4,role:'assistant',content:'',reasoning_details:{estimatedTokens:12}},
];
for(let i=0;i<3;i++) {
  unchanged(reasoning);
  assert.equal(build('fixture',reasoning).length,0);
  assert.equal(load(reasoning,'fixture').length,0);
}
assert.equal(warnings.length,0,'reasoning-only warning');
const valid=[{id:10,role:'user',content:'question'},
  {id:11,role:'assistant',content:'answer',reasoning_content:'private',reasoning_details:{estimatedTokens:1}},
  {id:12,role:'assistant',content:'',tool_calls:[{id:'call-1',type:'function',function:{name:'test',arguments:'{}'}}]},
  {id:13,role:'tool',content:'result',tool_call_id:'call-1',tool_name:'test'}];
unchanged(valid);
for(const out of [build('fixture',valid),load(valid,'fixture')]) {
  assert.equal(out.length,4); assert.equal(out[1].content,'answer');
  assert.equal(out[2].tool_calls[0].function.arguments,'{}');
  assert.equal(out[3].tool_call_id,'call-1'); assert.equal(out[3].content,'result');
}
if(layout.modern) {
  const thinking=[{type:'thinking',thinking:'private thinking'}];
  for(const content of [thinking,JSON.stringify(thinking),'"'+JSON.stringify(thinking)+'"']) {
    const rows=[{id:20,role:'assistant',content}];
    unchanged(rows); assert.equal(load(rows,'thinking').length,0);
  }
  assert.equal(warnings.length,0,'parsed thinking warning');
  for(const content of [[{type:'text',text:'answer'}],JSON.stringify([{type:'text',text:'answer'}]),
    [{type:'tool_use',id:'call-2',name:'test',input:{x:1}}],
    JSON.stringify([{type:'tool_use',id:'call-2',name:'test',input:{x:1}}])]) {
    unchanged([{id:21,role:'assistant',content}]);
    assert.equal(load([{id:21,role:'assistant',content}],'formats').length,1);
  }
  unchanged([{id:22,role:'assistant',content:'answer',display_role:'worker',display_content:'shown',finish_reason:null,run_marker:'run'}]);
  unchanged([...valid,{id:14,role:'user',content:'last user'},{id:15,role:'assistant',content:'later'}], 'exclude', {excludeLastUser:true});
  const out=build('cursor',valid,{truncateToolResults:false});
  assert.equal(out[1].cursorId,11); assert(!Object.keys(out[1]).includes('cursorId'));
  assert(!JSON.stringify(out).includes('cursorId'));
  assert.equal(out[1].reasoning_content,'private');
  const long=[{id:30,role:'tool',content:'x'.repeat(7000),tool_call_id:'call-1'}];
  unchanged(long); unchanged(long,'full',{truncateToolResults:false});
  assert(build('truncate',long)[0].content.length<7000);
  assert.equal(build('full',long,{truncateToolResults:false})[0].content.length,7000);
  // Inject only the external runtime projection boundary; execute real A0e/Frt.
  let projected=0;
  context.k0e={projectBrowserHistory:(rows,opts)=>{projected++; assert.equal(typeof opts.truncateOtherTools,'function'); return rows.map(r=>({...r,content:r.content+' projected'}));}};
  assert.equal(build('projection',[valid[1]])[0].content,'answer projected');
  assert.equal(projected,1); context.k0e=undefined;
  // Exercise actual full/cursor context functions using read-only DB fixtures.
  const db=[{id:1,role:'user',content:'head'}, {id:2,role:'assistant',content:'old'},
    {id:3,role:'assistant',content:'new'}, {id:4,role:'user',content:'tail'}];
  const reads=[];
  context.wM=(_session,opts={})=>{reads.push(opts); return db.filter(r=>(opts.throughId==null||r.id<=opts.throughId)&&(opts.afterId==null||r.id>opts.afterId)).slice(0,opts.limit??db.length);};
  context.Oe=()=>({history_revision:7}); context.KZ=(_s,id)=>db.some(r=>r.id===id);
  assert.equal(context.k_('db').length,4);
  const snapshot={compressedThroughMessageId:2,protectedHeadThroughMessageId:1,historyRevision:7,summary:'summary'};
  const cursor=context.sZ('db',snapshot,{excludeLastUser:true,truncateToolResults:false});
  assert.equal(cursor.status,'usable'); assert.equal(cursor.parts.head[0].cursorId,1);
  assert.equal(cursor.parts.newMessages[0].cursorId,3); assert.equal(cursor.parts.newMessages.length,1);
  assert.equal(context.Kv(snapshot,cursor.parts,'prefix')[1].content,'prefix\n\nsummary');
  assert.equal(context.sZ('db',{...snapshot,historyRevision:8}).reason,'history_revision_mismatch');
  assert.equal(context.sZ('db',{...snapshot,compressedThroughMessageId:999}).reason,'cursor_missing');
  assert.equal(context.sZ('db',null).status,'legacy');
  assert(reads.some(r=>r.afterId===2));
  console.log('PASS: 0.8.14 content formats, parsed thinking, cursor descriptors, full/cursor context, projection, truncation, excludeLastUser');
}
assert.equal(warnings.length,0);
for(let i=0;i<3;i++) {
  build('empty',[{id:70,role:'assistant',content:''}]);
  load([{id:70,role:'assistant',content:''}],'empty');
}
assert.equal(warnings.length,1,'cross-pass dedup failed');
build('empty',[{id:71,role:'assistant',content:''}]);
load([{id:70,role:'assistant',content:''}],'other');
assert.equal(warnings.length,3,'distinct original ids/session collapsed');
assert.deepEqual(warnings.slice(0,3).map(w=>[w[1],w[2]]),[[70,'empty'],[71,'empty'],[70,'other']], 'warning must use original row id and session');
unchanged([{id:72,role:'assistant',content:' ',reasoning:' ',reasoning_content:'',reasoning_details:[]}], 'blank');
assert.equal(warnings.length,4,'blank reasoning is genuinely empty');
// Session/id separators cannot collide.
build('a:b',[{id:'c',role:'assistant',content:''}]);
build('a',[{id:'b:c',role:'assistant',content:''}]);
assert.equal(warnings.length,6);
for(let id=0;id<1025;id++) build('eviction',[{id,role:'assistant',content:''}]);
assert.equal(vm.runInContext('ekkoEmptyHistoryWarnings.size',context),1024);
let count=warnings.length;
load([{id:1024,role:'assistant',content:''}],'eviction'); assert.equal(warnings.length,count);
load([{id:0,role:'assistant',content:''}],'eviction'); assert.equal(warnings.length,count+1);
assert(!JSON.stringify(warnings).includes('private'),'reasoning leaked');
console.log('PASS: real load/build functions; reasoning quiet; answer/tool chain preserved; differential outputs/input unchanged; session+original-id dedup; collision-safe keys; bounded 1024 FIFO eviction');
