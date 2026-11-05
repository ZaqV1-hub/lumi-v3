// Toda a API do simulador é interceptada: nenhum contato ou inferência real.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHECKOUT_QA_BROWSER?{executablePath:process.env.CHECKOUT_QA_BROWSER}:{}),args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const context=await browser.newContext({viewport:{width:1280,height:1000},colorScheme:'light'});
  const root=path.join(process.env.LOCALAPPDATA,'Lumi'),out=path.join(root,'chat-ui-qa');fs.mkdirSync(out,{recursive:true});
  const image=fs.readFileSync(path.join(root,'qa-image.png')),audio=fs.readFileSync(path.join(root,'qa-audio.wav'));
  let items=[],uploads=[],texts=[],status='lumi',counter=0,rejectNext=false,legacyHits=0;
  const errors=[];
  try{
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    // Simula a cópia antiga ainda disponível na URL sem versão do navegador.
    await page.route(/\/static\/client\.js$/,route=>{
      legacyHits++;return route.fulfill({body:execFileSync('git',['show','HEAD:web/client.js']),contentType:'application/javascript'});
    });
    await page.route('**/api/**',async route=>{
      const req=route.request(),url=new URL(req.url());
      if(url.pathname==='/api/public/rincao/start'){counter++;items=[];status='lumi';return route.fulfill({json:{token:'qa-chat-'+counter,tenant:'Rincão'}});}
      if(/^\/api\/client\/qa-chat-\d+$/.test(url.pathname))return route.fulfill({json:{status,blocked:false,messages:items}});
      if(url.pathname.endsWith('/attachments')){
        if(rejectNext){rejectNext=false;return route.fulfill({status:422,json:{detail:'Falha simulada para testar nova tentativa.'}});}
        const caption=decodeURIComponent(req.headers()['x-lumi-caption']||'');
        const image=req.headers()['content-type'].startsWith('image/');uploads.push({caption,type:req.headers()['content-type'],bytes:req.postDataBuffer().length});
        items.push({id:'media-'+uploads.length,sender:'cliente',content:caption||(image?'[Imagem enviada]':'[Transcrição do áudio]\nOlá Lumi.'),created_at:new Date().toISOString(),attachment_kind:image?'image':'audio',attachment_url:'/qa-media/'+(image?'image':'audio')});
        return route.fulfill({json:{ok:true}});
      }
      if(url.pathname.endsWith('/messages')){
        texts.push(req.postDataJSON().content);items.push({id:'text-'+texts.length,sender:'cliente',content:req.postDataJSON().content,created_at:new Date().toISOString()});return route.fulfill({json:{ok:true}});
      }
      throw Error('Requisição de API inesperada: '+url.pathname);
    });
    await page.route('**/qa-media/*',route=>route.fulfill({body:route.request().url().endsWith('/image')?image:audio,contentType:route.request().url().endsWith('/image')?'image/png':'audio/wav'}));
    const response=await page.goto('http://127.0.0.1:8000/chat/rincao');
    assert.equal(response.headers()['cache-control'],'no-store');
    assert.equal(await page.locator('script[src^="/static/"]').evaluateAll(nodes=>nodes.every(node=>/[?]v=[a-f0-9]{12}$/.test(node.src))),true);
    await page.locator('#name').fill('Teste visual');await page.getByRole('button',{name:'Conversar',exact:true}).click();
    await page.locator('.empty').waitFor();assert.equal(await page.locator('.row.lumi').count(),0);
    await page.reload();await page.locator('.empty').waitFor();assert.equal(await page.locator('#startOverlay').isVisible(),false);assert.equal(legacyHits,0);
    await page.locator('#file').setInputFiles(path.join(root,'qa-image.png'));await page.locator('#tray').waitFor();assert.equal(uploads.length,0);
    const caption='O que é essa imagem? Teste de legenda com acentuação.';
    await page.locator('#msg').fill(caption);await page.screenshot({path:path.join(out,'desktop-preview.png'),fullPage:true});
    await page.getByRole('button',{name:'Enviar mensagem',exact:true}).click();await page.locator('#thread .pic img').waitFor();
    assert.equal(uploads.length,1);assert.equal(uploads[0].caption,caption);assert.equal(uploads[0].bytes,image.length);assert.equal(texts.length,0);
    await page.locator('#thread .pic').click();await page.getByRole('button',{name:'Fechar imagem'}).click();
    await page.locator('#file').setInputFiles(path.join(root,'qa-image.png'));await page.getByRole('button',{name:'Remover imagem'}).click();assert.equal(uploads.length,1);
    await page.locator('#msg').fill('Mensagem só de texto');await page.locator('#msg').press('Enter');await page.waitForFunction(()=>document.querySelector('#msg').value==='');
    await page.locator('#thread').getByText('Mensagem só de texto',{exact:true}).waitFor();assert.equal(texts.length,1);
    rejectNext=true;await page.locator('#file').setInputFiles(path.join(root,'qa-image.png'));await page.locator('#msg').fill('Legenda preservada');
    await page.getByRole('button',{name:'Enviar mensagem',exact:true}).click();await page.locator('#notice').filter({hasText:'Falha simulada'}).waitFor();
    assert.equal(await page.locator('#msg').inputValue(),'Legenda preservada');assert.equal(await page.locator('#tray').isVisible(),true);
    await page.getByRole('button',{name:'Enviar mensagem',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#tray').hidden);assert.equal(uploads.length,2);
    await page.locator('#file').setInputFiles(path.join(root,'qa-audio.wav'));assert.equal(uploads.length,2);
    await page.getByRole('button',{name:'Enviar mensagem',exact:true}).click();await page.locator('#thread audio').waitFor();
    await page.getByRole('button',{name:'Gravar áudio',exact:true}).click();await page.locator('#recGo:not([disabled])').waitFor();
    await page.waitForFunction(()=>document.querySelector('#recT').textContent==='0:01');await page.getByRole('button',{name:'Enviar áudio',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#thread audio').length===2);assert.equal(uploads.length,4);
    await page.getByRole('button',{name:'Gravar áudio',exact:true}).click();await page.locator('#recGo:not([disabled])').waitFor();await page.getByRole('button',{name:'Cancelar gravação'}).click();assert.equal(uploads.length,4);
    items.push({id:'system',sender:'sistema',content:'Isaque assumiu a conversa.',created_at:new Date().toISOString()},{id:'operator',sender:'humano',name:'Isaque',content:'Oi! Vou continuar seu atendimento por aqui. https://example.com/'+('a'.repeat(180)),created_at:new Date().toISOString()});status='humano';
    await page.locator('#status').filter({hasText:'Atendimento humano'}).waitFor();await page.locator('#thread strong').filter({hasText:'Isaque'}).waitFor();
    await page.screenshot({path:path.join(out,'desktop-chat.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile-chat.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('#thread').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
    await page.emulateMedia({colorScheme:'dark'});await page.screenshot({path:path.join(out,'mobile-dark.png'),fullPage:true});
    await page.getByRole('button',{name:'Nova conversa',exact:true}).click();await page.locator('#overlay').getByRole('button',{name:'Nova conversa',exact:true}).click();
    await page.locator('#startOverlay').waitFor();assert.equal(uploads.length,4);assert.equal(errors.length,0,errors.join('; '));
    console.log(JSON.stringify({oldCachedScriptIgnored:true,sessionRestored:true,imageWithCaption:true,noAutoUpload:true,retryKeepsDraft:true,audioUpload:true,microphone:true,cancelRecording:true,humanStatus:true,newConversation:true,mobileNoOverflow:true,realModelCalls:0,screenshots:out}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
