// Execute the shipped history functions, not a reimplementation; no database access.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
// Keep reviewed layouts explicit: minifier names are not stable across releases.
const layouts = [
  {anchor:'function t8e(t){', start:'function Omr(', end:'function $x(', load:'Umr', build:'r8e', truncate:'NZe', limit:'qx'},
  {anchor:'function W8e(t){', start:'function bpr(', end:'function rS(', load:'gpr', build:'y8e', truncate:'CZe', limit:'tS'},
].filter(layout => source.split(layout.anchor).length === 2);
assert.equal(layouts.length,1,'expected one reviewed history layout');
const layout = layouts[0];
const start = source.indexOf(layout.start);
const end = source.indexOf(layout.end, start);
assert(start >= 0 && end > start, 'history function boundaries changed');
const warnings = [];
const context = {C:{warn:(...args)=>warnings.push(args),info:()=>{}}, [layout.truncate]:x=>x, [layout.limit]:0};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
const load = context[layout.load];
const build = context[layout.build];
assert.equal(typeof load,'function','load history function missing');
assert.equal(typeof build,'function','build history function missing');
// The loader catches exceptions: prove it processes each fixture, not just [].
const reasoning = [{id:1,role:'assistant',content:'',reasoning:'private reasoning'}, {id:2,role:'assistant',content:' ',reasoning_content:'private reasoning'}, {id:3,role:'assistant',content:'',reasoning_details:[{type:'reasoning',text:'private'}]}];
for (let i=0;i<3;i++) {
  assert.equal(build('fixture', reasoning).length,0);
  assert.equal(load(reasoning,'fixture').length,0);
}
assert.equal(warnings.length,0,'reasoning-only history must not generate empty-message warnings');
const valid=[{id:4,role:'assistant',content:'answer'},{id:5,role:'assistant',content:'',tool_calls:[{id:'call-1',type:'function',function:{name:'test',arguments:'{}'}}]},{id:6,role:'tool',content:'result',tool_call_id:'call-1'}];
assert.equal(build('fixture',valid).length,3);
assert.equal(load(valid,'fixture').length,3);
for (const output of [build('fixture',valid), load(valid,'fixture')]) {
  assert.equal(output[0].content,'answer');
  assert.equal(output[1].tool_calls[0].id,'call-1');
  assert.equal(output[1].tool_calls[0].function.arguments,'{}');
  assert.equal(output[2].tool_call_id,'call-1');
  assert.equal(output[2].content,'result');
}
const before=JSON.stringify(valid);
build('fixture',valid);load(valid,'fixture');assert.equal(JSON.stringify(valid),before);
for(let i=0;i<3;i++) {build('fixture',[{id:7,role:'assistant',content:''}]);load([{id:7,role:'assistant',content:''}],'fixture');}
assert.equal(warnings.length,1,'genuine empty message warns once across load/build passes');
assert(!JSON.stringify(warnings).includes('private'),'never log reasoning payloads');
console.log('PASS: reasoning-only skipped quietly; valid answer/tool chain preserved; genuine empty warning deduplicated; input unchanged');
