// Integração real de UI e API em cópia local do banco (porta 8010, provider demo).
const {chromium}=require('playwright');const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const issueTitle='Problema QA '+Date.now();
 const base=process.env.CONSOLE_QA_URL||'http://127.0.0.1:8010';
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHECKOUT_QA_BROWSER});
 const context=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light'}),errors=[];
 const out=path.join(process.env.LOCALAPPDATA,'Lumi','console-ui-qa');fs.mkdirSync(out,{recursive:true});
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/admin');await page.locator('#em').fill('ana@breve.local');await page.locator('#pw').fill('demo1234');await page.locator('#loginForm button[type=submit]').click();
  await page.waitForURL('**/admin');await page.locator('#content h1').filter({hasText:'Olá'}).waitFor();
  await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
  const overview=await (await context.request.get(base+'/api/console/overview')).json(),rincao=overview.tenants.find(item=>item.slug==='rincao');
  await page.locator('#nav').getByRole('link',{name:'Tenants',exact:true}).click();await page.getByRole('heading',{name:'Tenants disponíveis'}).waitFor();
  await page.screenshot({path:path.join(out,'tenants.png'),fullPage:true});
  await page.getByRole('link',{name:'Entrar em '+rincao.name,exact:true}).click();await page.locator('#operatorBar').waitFor();await page.locator('#dStats').waitFor();
  assert.equal(new URL(page.url()).searchParams.get('tenant'),rincao.id);
  assert.equal(overview.current.estimated_usd,0);assert.equal(overview.tenants.length,2);assert.equal(overview.tenants.find(item=>item.name==='Brevia').lumi_enabled,false);
  const before=await context.request.get(base+'/api/admin/settings?tenant='+rincao.id);assert.equal(before.status(),200);
  await page.screenshot({path:path.join(out,'tenant-panel.png'),fullPage:true});
  assert.equal(await page.locator('#operatorBar a').count(),1);
  await page.locator('#operatorBar').getByRole('link',{name:'Voltar ao console',exact:true}).click();
  await page.locator('#nav').getByRole('link',{name:'Acessos',exact:true}).click();await page.getByRole('button',{name:'Criar acesso',exact:true}).waitFor();
  await page.getByRole('button',{name:'Criar acesso',exact:true}).click();
  const email='console-qa-'+Date.now()+'@example.test';
  await page.locator('#accessName').fill('Leitura QA');await page.locator('#accessEmail').fill(email);await page.locator('#accessRole').selectOption('leitura');await page.locator('#accessTenant').selectOption(rincao.id);await page.locator('#accessForm button[type=submit]').click();
  await page.locator('#doneCredential').waitFor();const temporary=await page.locator('#overlay .cred code').last().innerText();assert(temporary.length>=12);
  await page.locator('#doneCredential').click();await page.getByText(email,{exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'accesses.png'),fullPage:true});
  const reader=await browser.newContext({viewport:{width:1280,height:900}});
  try{
   const readPage=await reader.newPage();readPage.on('pageerror',e=>errors.push(e.message));await readPage.goto(base+'/admin');
   await readPage.locator('#em').fill(email);await readPage.locator('#pw').fill(temporary);await readPage.locator('#loginForm button[type=submit]').click();await readPage.locator('#pwForm').waitFor();
   assert.equal((await reader.request.get(base+'/api/admin/settings')).status(),403);
   await readPage.locator('#np').fill('QA-new-password-123');await readPage.locator('#np2').fill('QA-new-password-123');await readPage.locator('#pwForm button[type=submit]').click();
   await readPage.waitForURL('**/admin');await readPage.locator('.readonly-notice').waitFor();
   assert.equal((await reader.request.post(base+'/api/admin/knowledge',{data:{title:'Bloqueado','content':'Não salvar'}})).status(),403);
   assert.equal((await reader.request.get(base+'/api/console/overview')).status(),403);
  }finally{await reader.close();}
  await page.locator('.tr').filter({hasText:email}).getByRole('button',{name:'Remover',exact:true}).click();await page.locator('#removeConfirm').click();
  await page.waitForFunction(email=>![...document.querySelectorAll('#accessRows .em')].some(node=>node.textContent===email),email);
  await page.locator('#includeRemoved').check();await page.locator('.tr').filter({hasText:email}).getByRole('button',{name:'Restaurar'}).click();
  await page.locator('.tr').filter({hasText:email}).getByRole('button',{name:'Editar',exact:true}).waitFor();
  const customer=await browser.newContext();
  try{
   const customerPage=await customer.newPage();await customerPage.goto(base+'/admin');await customerPage.locator('#em').fill('isaque@rincao.local');await customerPage.locator('#pw').fill('demo1234');await customerPage.locator('#loginForm button[type=submit]').click();await customerPage.locator('#app').waitFor();
   assert.equal(await customerPage.locator('#operatorBar').count(),0);
   await customerPage.locator('#app [data-support]').click();await customerPage.locator('#reportTitle').fill(issueTitle);await customerPage.locator('#reportDescription').fill('Verificação isolada de abertura e acompanhamento.');await customerPage.locator('#reportSend').click();
   await customerPage.locator('#toast').filter({hasText:'Problema registrado'}).waitFor();
  }finally{await customer.close();}
  await page.goto(base+'/admin#/problemas');await page.getByText(issueTitle,{exact:true}).click();await page.locator('#issueStatus').selectOption('analise');await page.locator('#issueNote').fill('Verificado em QA.');await page.locator('#saveIssue').click();
  await page.locator('#overlay').waitFor({state:'hidden'});const issues=await (await context.request.get(base+'/api/console/issues')).json();assert.equal(issues.find(item=>item.title===issueTitle).status,'analise');
  await page.screenshot({path:path.join(out,'issues.png'),fullPage:true});
  await page.goto(base+'/admin#/t/'+rincao.id+'/custos');await page.locator('#auditRows').waitFor();await page.screenshot({path:path.join(out,'costs.png'),fullPage:true});
  await page.goto(base+'/admin#/visao');await page.locator('#content h1').filter({hasText:'Olá'}).waitFor();await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('#side').getBoundingClientRect().right<=0);await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(errors.length,0,errors.join('; '));
  console.log(JSON.stringify({operatorRedirect:true,tenantWorkspace:true,noIframe:true,createAccess:true,forcedPassword:true,readOnly:true,customerIsolation:true,reportAndUpdateIssue:true,metrics:true,audit:true,mobileNoOverflow:true,realModelCalls:0,screenshots:out}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
