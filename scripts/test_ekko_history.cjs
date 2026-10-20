// Execute the shipped history functions, not a reimplementation; no database access.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('function Omr(');
const end = source.indexOf('function $x(', start);
assert(start >= 0 && end > start, 'history function boundaries changed');
const warnings = [];
const context = {C:{warn:(...args)=>warnings.push(args),info:()=>{}}, NZe:x=>x, EDn:x=>x, qx:0};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
const reasoning = [{id:1,role:'assistant',content:'',reasoning:'private reasoning'}, {id:2,role:'assistant',content:' ',reasoning_content:'private reasoning'}, {id:3,role:'assistant',content:'',reasoning_details:[{type:'reasoning',text:'private'}]}];
for (let i=0;i<3;i++) {
  assert.equal(context.r8e('fixture', reasoning).length,0);
  assert.equal(context.Umr(reasoning,'fixture').length,0);
}
assert.equal(warnings.length,0,'reasoning-only history must not generate empty-message warnings');
const valid=[{id:4,role:'assistant',content:'answer'},{id:5,role:'assistant',content:'',tool_calls:[{id:'call-1',type:'function',function:{name:'test',arguments:'{}'}}]},{id:6,role:'tool',content:'result',tool_call_id:'call-1'}];
assert.equal(context.r8e('fixture',valid).length,3);
assert.equal(context.Umr(valid,'fixture').length,3);
const before=JSON.stringify(valid);
context.r8e('fixture',valid);assert.equal(JSON.stringify(valid),before);
for(let i=0;i<3;i++) {context.r8e('fixture',[{id:7,role:'assistant',content:''}]);context.Umr([{id:7,role:'assistant',content:''}],'fixture');}
assert.equal(warnings.length,1,'genuine empty message warns once across load/build passes');
assert(!JSON.stringify(warnings).includes('private'),'never log reasoning payloads');
console.log('PASS: reasoning-only skipped quietly; valid answer/tool chain preserved; genuine empty warning deduplicated; input unchanged');
