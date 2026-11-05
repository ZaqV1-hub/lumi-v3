const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const message = (sender, created_at) => ({sender, created_at});
const context = vm.createContext({ui: {}, convos: [
  {id:'wa',channel:'whatsapp',status:'lumi',created_at:'2026-10-31T12:00:00Z',messages:[
    message('cliente','2026-11-02T15:00:00Z'),message('cliente','2026-11-02T15:01:00Z'),
    message('lumi','2026-11-02T15:02:00Z')]},
  {id:'ig',channel:'instagram',status:'humano',created_at:'2026-11-01T12:00:00Z',messages:[
    message('cliente','2026-11-03T02:59:59Z'),message('humano','2026-11-03T03:10:00Z')]},
  {id:'inactive',channel:'simulator',status:'lumi',created_at:'2026-10-30T12:00:00Z',messages:[
    message('cliente','2026-11-01T12:00:00Z'),message('lumi','2026-11-02T12:00:00Z')]},
  {id:'empty',channel:'simulator',status:'lumi',created_at:'2026-11-02T12:00:00Z',messages:[]},
  {id:'comment',channel:'instagram_comment',status:'lumi',created_at:'2026-11-01T12:00:00Z',messages:[
    message('cliente','2026-11-02T12:00:00Z')]},
]});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/admin-dashboard.js'),'utf8'),context);
Object.assign(context.ui,{period:'custom',from:'2026-11-02',to:'2026-11-02'});
let result=context.stats();
assert.equal(result.att,3); // Existing conversations count once, regardless of message volume.
assert.equal(result.msg,4);
assert.equal(result.opened,1);
assert.equal(result.total,5);
assert.equal(result.wa,0);
assert.equal(result.ig,1);
assert.equal(result.instagram,1);
assert.equal(result.comments,1);
assert.equal(result.topics.find(([label])=>label==='Atendimento humano')[1],1);
context.ui.from=context.ui.to='2026-11-03';
result=context.stats();
assert.equal(result.att,0); // An operator reply alone does not count as a customer's visit.
assert.equal(result.msg,0);
context.ui.from='2026-11-01';context.ui.to='2026-11-02';
result=context.stats();
assert.equal(result.att,4); // A conversation counts once across a multi-day period, too.
assert.equal(result.msg,5);
console.log('Dashboard: atividade, novos, histórico, canais e fuso de São Paulo verificados.');
