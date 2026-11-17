const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class DashboardDate extends Date {
  constructor(...args) { super(...(args.length ? args : ['2026-11-03T02:30:00Z'])); }
}

const requests = [];
const painted = [];
const elements = new Map();
const context = vm.createContext({
  Date: DashboardDate,
  URLSearchParams,
  AbortSignal,
  ui: {},
  me: {tenant:'Empresa de teste'},
  page: () => 'dashboard',
  assistantName: () => 'Lumi',
  adminDataStatus: () => {},
  updateHandoverCount: () => {},
  fmtBR: value => value,
  $: selector => {
    if (!elements.has(selector)) elements.set(selector, {});
    return elements.get(selector);
  },
  api: path => new Promise(resolve => requests.push({path, resolve})),
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/admin-dashboard.js'),'utf8'),context);
context.paintStats = data => painted.push(data);
context.renderRecent = () => {};

(async () => {
  const first = context.drawStats();
  assert.equal(requests[0].path, '/api/admin/dashboard?start=2026-11-02&end=2026-11-02');
  context.ui.period = '7d';
  const weekly = context.drawStats();
  assert.equal(requests[1].path, '/api/admin/dashboard?start=2026-10-27&end=2026-11-02');
  context.ui.period = '30d';
  const monthly = context.drawStats();
  assert.equal(requests[2].path, '/api/admin/dashboard?start=2026-10-04&end=2026-11-02');
  requests[2].resolve({att: 13});
  requests[0].resolve({att: 1});
  requests[1].resolve({att: 5});
  await Promise.all([first, weekly, monthly]);
  assert.deepEqual(painted, [{att: 13}]);
  console.log('Dashboard: consultas por período e descarte de respostas antigas verificados.');
})().catch(error => {console.error(error); process.exitCode = 1;});