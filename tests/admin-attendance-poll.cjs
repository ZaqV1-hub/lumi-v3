const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let count=0,calls=0;
const context={me:{tenant_id:'example'},document:{hidden:false},page:()=> 'configuracoes',AbortSignal,
 api:async path=>{assert.equal(path,'/api/admin/attendance/waiting');calls++;return {waiting_count:3};},
 updateHandoverCount:value=>{count=value;return true;}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/admin-conversation-data.js','utf8'),context);
(async()=>{await context.refresh();assert.equal(calls,1);assert.equal(count,3);context.document.hidden=true;await context.refresh();assert.equal(calls,1);console.log('Waiting count refreshes outside conversations');})().catch(error=>{console.error(error);process.exitCode=1;});
