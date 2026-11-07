// Executar somente contra uma cópia PostgreSQL local com provider demo.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');

(async()=>{
  const base=process.env.LUMI_QA_URL||'http://127.0.0.1:8011';
  assert.equal(new URL(base).hostname,'127.0.0.1','QA deve usar loopback');
  const credentials=JSON.parse(fs.readFileSync(process.env.LUMI_QA_CREDENTIALS,'utf8'));
  const out=path.resolve('.data/postgres-ui');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHECKOUT_QA_BROWSER});
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),errors=[];
  await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  try {
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/admin');
    await page.locator('#em').fill(credentials.email);await page.locator('#pw').fill(credentials.password);
    await page.locator('#loginForm button[type=submit]').click();
    await page.locator('#content h1').filter({hasText:'Olá'}).waitFor();
    const overview=await (await context.request.get(base+'/api/console/overview')).json();
    const tenant=overview.tenants.find(t=>t.slug===process.env.LUMI_QA_TENANT);
    assert(tenant,'Tenant de QA deve estar listado');
    const usage=await (await context.request.get(base+'/api/admin/usage?tenant='+tenant.id)).json();
    assert.equal(usage.configured_provider,'demo','Não executar inferência real no QA');
    await page.screenshot({path:path.join(out,'console-desktop.png'),fullPage:true});
    await page.locator('#nav').getByRole('link',{name:'Clientes',exact:true}).click();
    await page.getByRole('link',{name:'Entrar em '+tenant.name,exact:true}).click();
    await page.locator('#dStats').waitFor();
    const settings=await context.request.get(base+'/api/admin/settings?tenant='+tenant.id);
    assert.equal(settings.status(),200);assert((await settings.json()).identity.length>0);
    const images=await (await context.request.get(base+'/api/admin/images?tenant='+tenant.id)).json();
    assert(images.length>0);
    for(const img of images){const r=await context.request.get(base+img.src+'?tenant='+tenant.id);assert.equal(r.status(),200);assert((await r.body()).length>0);}
    await page.screenshot({path:path.join(out,'tenant-desktop.png'),fullPage:true});
    const chat=await context.newPage();chat.on('pageerror',e=>errors.push(e.message));
    await chat.goto(base+'/chat/'+tenant.slug);await chat.locator('#name').fill('Pessoa QA local');
    await chat.locator('#start button[type=submit]').click();
    await chat.locator('#startOverlay').waitFor({state:'hidden'});
    await chat.locator('#msg').fill('Olá, teste local no PostgreSQL.');await chat.locator('#go').click();
    await chat.locator('#thread').getByText(/modo de demonstração/).waitFor();
    await chat.locator('#file').setInputFiles(path.resolve('.data/qa-image.png'));
    await chat.locator('#tray').waitFor();await chat.locator('#msg').fill('Imagem fictícia para teste.');
    const upload=chat.waitForResponse(r=>r.url().includes('/attachments')&&r.request().method()==='POST');
    await chat.locator('#go').click();assert.equal((await upload).status(),200);
    await chat.screenshot({path:path.join(out,'chat-desktop.png'),fullPage:true});
    await chat.reload();await chat.locator('#thread').getByText('Olá, teste local no PostgreSQL.').waitFor();
    await chat.setViewportSize({width:390,height:844});
    assert(await chat.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await chat.screenshot({path:path.join(out,'chat-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({login:true,importedSettings:true,importedImages:images.length,
      simulator:true,imageUpload:true,reloadHistory:true,mobileNoOverflow:true,pageErrors:0,realModelCalls:0}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
