// Usa uma cópia do banco e apenas leituras; nenhuma inferência ou conversa nova.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
(async()=>{
 const base=process.env.CONSOLE_QA_URL||'http://127.0.0.1:8010',browser=await chromium.launch({headless:true,executablePath:process.env.CHECKOUT_QA_BROWSER});
 const context=await browser.newContext({viewport:{width:1540,height:1100},colorScheme:'light',locale:'pt-BR',reducedMotion:'reduce'}),errors=[];
 const out=path.join(process.env.LOCALAPPDATA,'Lumi','usage-report-qa');fs.mkdirSync(out,{recursive:true});
 try{
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await context.request.post(base+'/api/login',{data:{email:'ana@breve.local',password:'demo1234'}});
  const overview=await (await context.request.get(base+'/api/console/overview')).json(),rincao=overview.tenants.find(item=>item.slug==='rincao');
  await page.goto(base+'/admin?tenant='+rincao.id+'#consumo');await page.locator('#exportUsage').waitFor();
  assert.equal(await page.locator('#usageNav').isVisible(),true);assert.equal(await page.locator('#usageNav').getAttribute('aria-current'),'page');
  assert.equal(await page.locator('.usage-current h3').innerText(),'gpt-6.1-terra');
  assert.equal(await page.locator('.usage-kpi').count(),4);assert.equal(await page.locator('.usage-charts').count(),1);
  await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  await page.locator('#usageModel').selectOption('gpt-6.1-terra');
  await page.waitForFunction(()=>document.querySelector('#usageBody').getAttribute('aria-busy')==='false');
  assert.equal(await page.locator('.usage-table').first().locator('tbody tr').count(),1);
  assert((await page.locator('.usage-table').first().locator('tbody tr').innerText()).includes('gpt-6.1-terra'));
  const download=page.waitForEvent('download');await page.locator('#exportUsage').click();const file=await download;const csv=fs.readFileSync(await file.path(),'utf8');assert(csv.includes('gpt-6.1-terra'));assert(!csv.includes('gpt-6.1-sol'));
  await page.locator('#usageModel').selectOption('');await page.waitForFunction(()=>document.querySelector('#usageBody').getAttribute('aria-busy')==='false');
  await page.locator('#usagePeriod').selectOption('30d');await page.waitForFunction(()=>document.querySelector('#usageBody').getAttribute('aria-busy')==='false');
  await page.setViewportSize({width:390,height:844});await page.locator('#content').evaluate(node=>node.scrollTop=0);await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.emulateMedia({colorScheme:'dark'});await page.screenshot({path:path.join(out,'mobile-dark.png'),fullPage:true});
  await page.locator('#usageFrom').fill('2000-01-01');await page.locator('#usageTo').fill('2000-01-02');await page.locator('#refreshUsage').click();await page.waitForFunction(()=>document.querySelector('#usageBody').getAttribute('aria-busy')==='false');
  await page.getByText('Nenhuma chamada encontrada para esses filtros.',{exact:true}).waitFor();
  await page.setViewportSize({width:1540,height:1100});await page.emulateMedia({colorScheme:'light'});
  await page.goto(base+'/admin?tenant='+rincao.id+'#configuracoes');await page.getByRole('tab',{name:'Instruções',exact:true}).waitFor();assert.equal(await page.getByRole('tab',{name:'Consumo e velocidade',exact:true}).count(),0);
  const customer=await browser.newContext();
  try{
   await customer.request.post(base+'/api/login',{data:{email:'isaque@rincao.local',password:'demo1234'}});
   const clientPage=await customer.newPage();clientPage.on('pageerror',error=>errors.push(error.message));await clientPage.goto(base+'/admin#consumo');await clientPage.locator('#dStats').waitFor();
   assert.equal(await clientPage.locator('#usageNav').isVisible(),false);assert.equal(await clientPage.locator('.nav a:visible').count(),3);
   assert.equal((await customer.request.get(base+'/api/admin/usage')).status(),403);
   assert.equal((await customer.request.get(base+'/api/admin/usage?tenant='+rincao.id)).status(),403);
   assert.equal(new URL(clientPage.url()).hash,'#dashboard');
  }finally{await customer.close();}
  assert.equal(errors.length,0,errors.join('; '));console.log(JSON.stringify({separateMenu:true,breviaOnly:true,customerHasThreeItems:true,configuredModel:true,modelFilter:true,dateFilter:true,charts:true,csv:true,emptyState:true,mobileNoOverflow:true,realModelCalls:0,screenshots:out}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
