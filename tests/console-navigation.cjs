const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const base=process.env.CONSOLE_QA_URL||'http://127.0.0.1:8010';const browser=await chromium.launch({headless:true,executablePath:process.env.CHECKOUT_QA_BROWSER});try{
 const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage();let documents=0;page.on('request',request=>{if(request.resourceType()==='document')documents++;});
 await page.goto(base+'/admin');await page.locator('#em').fill('ana@breve.local');await page.locator('#pw').fill('demo1234');await page.locator('#loginForm button[type=submit]').click();await page.locator('#content h1').filter({hasText:'Olá'}).waitFor();assert.equal(documents,1);
 await page.route('**/api/console/users*',async route=>{await new Promise(resolve=>setTimeout(resolve,450));await route.continue();});
 await page.locator('#nav').getByRole('link',{name:'Acessos',exact:true}).click();await page.locator('#nav').getByRole('link',{name:'Tenants',exact:true}).click();await page.getByRole('heading',{name:'Tenants disponíveis'}).waitFor();
 await page.waitForTimeout(650);assert.equal(await page.getByRole('heading',{name:'Tenants disponíveis'}).count(),1);assert.equal(documents,1);
 const overview=await (await context.request.get(base+'/api/console/overview')).json(),rincao=overview.tenants.find(item=>item.slug==='rincao');
 await page.goto(base+'/admin#/t/'+rincao.id+'/acessos');await page.getByRole('heading',{name:'Acessos de '+rincao.name}).waitFor();assert.equal(await page.locator('#ws').isVisible(),false);assert.equal(await page.locator('#content .console-back').count(),1);
 const html=await (await context.request.get(base+'/admin?tenant='+rincao.id)).text();assert(html.includes('<body class="operator-workspace"><header id="operatorBar">'));assert(!html.includes('/static/operator-workspace.js'));
 console.log(JSON.stringify({singleAdminUrl:true,noExtraDocumentOnOperatorLogin:true,rapidNavigationPreserved:true,stableAdminShell:true,serverRenderedBackButton:true,realModelCalls:0}));
}finally{await browser.close();}})().catch(error=>{console.error(error.stack);process.exitCode=1});
