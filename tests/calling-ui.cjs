// Loopback-only fixtures: no application database, real recipient or Meta requests.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),out=path.join(root,'output/playwright/calling');
(async()=>{
  const server=http.createServer((req,res)=>{
    const pathname=new URL(req.url,'http://localhost').pathname;
    if(pathname==='/peer'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Local audio peer</title>');return;}
    const file=pathname==='/admin'?'admin.html':pathname.startsWith('/static/')?pathname.slice(8):null;
    if(!file||file.includes('..')||!fs.existsSync(path.join(root,'web',file))){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'web',file)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port;
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHECKOUT_QA_BROWSER,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage(),errors=[],posts=[];
  page.on('pageerror',e=>errors.push(e.message));
  let permission='absent',available=true,owner=true,active=null,call=null,answer=null,uncertain=false,rootDelay=0,logoutReleased=false,lookupNullOnce=false;
  const remote=await context.newPage();
  await remote.goto(base+'/peer');
  await page.addInitScript(()=>{
    window.qaPeers=[]; window.qaTracks=[]; window.qaRejections=[];
    window.addEventListener('unhandledrejection',event=>window.qaRejections.push(String(event.reason?.message||event.reason)));
    const Peer=window.RTCPeerConnection,media=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.RTCPeerConnection=class extends Peer{constructor(...args){super(...args);window.qaPeers.push(this);if(window.qaIceFailure)Object.defineProperty(this,'iceGatheringState',{get:()=> 'gathering'});}};
    navigator.mediaDevices.getUserMedia=async options=>{if(window.qaDenyMic)throw new DOMException('Denied fixture','NotAllowedError');const stream=await media(options);window.qaTracks.push(...stream.getTracks());return stream;};
  });
  const convo={id:'conversation-demo',name:'Nome não informado',contact_id:'contact-demo',channel:'whatsapp',status:'humano',role:'cliente',profile:{},messages:[]};
  await context.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.origin!==base)return route.abort();
    if(!url.pathname.startsWith('/api/'))return route.continue();
    let data;
    if(url.pathname.includes('/calling')){
      if(req.method()==='POST'){assert.equal(req.headers().origin,base);posts.push({url:url.pathname,body:req.postDataJSON(),tab:req.headers()['x-calling-tab'],tenant:url.searchParams.get('tenant')});}
      if(url.pathname.endsWith('/calling')){if(rootDelay)await new Promise(r=>setTimeout(r,rootDelay));data={enabled:available,can_call:available&&owner&&permission==='granted'&&!active,can_request_permission:available&&owner&&['absent','granted'].includes(permission),block_reason:!available?'Chamadas indisponíveis neste canal.':!owner?'Assuma o atendimento para ligar.':null,permission:{state:permission,expires_at:null},active_call:active,history:[{id:'historical-demo',state:'ended',active:false,created_at:'2026-11-10T12:00:00Z',connected_at:null,ended_at:'2026-11-10T12:01:00Z',operator_name:'Operadora <teste>',error_code:null}]};}
      else if(url.pathname.endsWith('/permission')){permission='pending';data={id:'permission-demo',state:'sent',active:true,version:1};}
      else if(url.pathname.endsWith('/calls')){
        const offer=req.postDataJSON().sdp_offer;
        assert.match(offer,/a=rtpmap:\d+ opus\/48000\/2/);assert.match(offer,/a=ptime:20/);assert.match(offer,/a=candidate:/);assert.equal((offer.match(/^m=/gm)||[]).length,1);
        assert.match(req.headers()['x-calling-tab'],/^[A-Za-z0-9_-]{32,128}$/);
        call={id:'call-demo',state:'ringing',active:true,version:1,browser_state:'new',connected_at:null,ended_at:null,error_code:null};active={...call};
        answer=await remote.evaluate(async offer=>{
          window.remotePeer?.close();window.remoteStream?.getTracks().forEach(t=>t.stop());
          const peer=window.remotePeer=new RTCPeerConnection({iceServers:[]});
          window.remoteStream=await navigator.mediaDevices.getUserMedia({audio:true,video:false});
          peer.addTrack(remoteStream.getAudioTracks()[0],remoteStream);await peer.setRemoteDescription({type:'offer',sdp:offer});await peer.setLocalDescription(await peer.createAnswer());
          await new Promise(resolve=>{if(peer.iceGatheringState==='complete')return resolve();peer.onicegatheringstatechange=()=>{if(peer.iceGatheringState==='complete')resolve();};});return peer.localDescription.sdp;
        },offer);
        data={...call,tab_token:req.headers()['x-calling-tab']};
        if(uncertain){const mode=uncertain;uncertain=false;if(mode==='terminal'||mode==='delayed'){call={...call,state:'rejected',active:false,version:2,answer_sdp:null};active=null;lookupNullOnce=mode==='delayed';}return mode==='http'?route.fulfill({status:500,json:{detail:'fixture'}}):route.abort();}
      }else if(url.pathname.includes('/calls/by-key/')){
        const original=posts.filter(p=>p.url.endsWith('/calls')).at(-1);
        assert.equal(decodeURIComponent(url.pathname.split('/').at(-1)),original.body.idempotency_key);assert.equal(req.headers()['x-calling-tab'],original.tab);assert.equal(url.searchParams.get('tenant'),original.tenant);
        data={call:lookupNullOnce?null:{...call,answer_sdp:call.active?answer:null}};lookupNullOnce=false;
      }else if(url.pathname.endsWith('/heartbeat')){assert(['new','connecting','connected','disconnected','failed','closed'].includes(req.postDataJSON().browser_state));data=call;}
      else if(url.pathname.endsWith('/terminate')){call={...call,state:'ended',active:false,version:3};active=null;data=call;}
      else if(url.pathname.endsWith('/calls/call-demo'))data={...call,answer_sdp:answer};
      else throw Error('Unexpected calling URL '+url.pathname);
    }else if(url.pathname==='/api/me')data={name:'Operadora teste',tenant:'Empresa fictícia',assistant_name:'Ana',tenant_id:'tenant-demo',slug:'demo',role:'operador',lumi_enabled:true};
    else if(url.pathname.endsWith('/conversations'))data=[convo];
    else if(url.pathname.endsWith('/settings'))data={};
    else if(url.pathname.endsWith('/role-instructions'))data=[{role:'cliente',label:'Cliente'}];
    else if(url.pathname==='/api/logout'){logoutReleased=await page.evaluate(()=>window.qaTracks.length>0&&window.qaTracks.every(t=>t.readyState==='ended')&&window.qaPeers.every(p=>p.connectionState==='closed'));data={ok:true};}
    else data=[];
    return route.fulfill({json:data});
  });
  try{
    await page.goto(base+'/admin?tenant=tenant-demo#conversas');
    await page.getByRole('button',{name:'Devolver à Ana',exact:true}).waitFor();
    assert.equal(await page.locator('.tenant .status').textContent(),'Ana ativa');
    const search = page.getByRole('textbox',{name:'Buscar por nome ou ID'});
    await search.fill('id-sem-correspondencia');
    await page.getByText('Nenhuma conversa neste filtro.').waitFor();
    await search.fill('#contact-demo');
    await page.locator('.c-item').getByText('#contact-demo',{exact:true}).waitFor();
    assert.equal(await page.locator('.c-item').getByText('Nome não informado',{exact:true}).count(),0);
    await search.fill('');
    await page.getByRole('button',{name:'Com atendente'}).click();
    assert.equal(await page.getByRole('button',{name:'Com atendente'}).getAttribute('aria-pressed'),'true');
    await page.getByRole('button',{name:'Todas',exact:true}).click();
    await page.getByText('Chamadas recentes',{exact:true}).click();await page.getByText('Operadora <teste>',{exact:false}).waitFor();assert.equal(await page.locator('.calling-history teste').count(),0);
    await page.getByRole('button',{name:'Pedir permissão',exact:true}).click({timeout:3000});
    await page.locator('#calling-controls').getByText('Aguardando permissão').waitFor();
    assert.equal(posts.length,1);assert.equal(posts[0].tenant,'tenant-demo');assert(posts[0].body.idempotency_key);
    permission='denied';await page.locator('#calling-controls').getByText('Permissão recusada',{exact:true}).waitFor();assert(await page.getByRole('button',{name:'Ligar pelo WhatsApp',exact:true}).isDisabled());
    available=false;await page.getByText('Chamadas indisponíveis neste canal.',{exact:true}).waitFor();
    available=true;owner=false;await page.getByText('Assuma o atendimento para ligar.',{exact:true}).waitFor();
    owner=true;permission='granted';await page.getByRole('button',{name:'Ligar pelo WhatsApp',exact:true}).waitFor();
    const start=page.getByRole('button',{name:'Ligar pelo WhatsApp',exact:true});
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    assert(await page.getByRole('button',{name:'Pedir permissão',exact:true}).isDisabled());
    convo.name='Isaque';
    await page.locator('.c-item').getByText('Isaque',{exact:true}).waitFor();
    await page.evaluate(()=>{window.qaDenyMic=true;});await start.click();
    await page.getByRole('alert').filter({hasText:'Microfone bloqueado'}).waitFor();assert.equal(await page.evaluate(()=>document.activeElement.classList.contains('calling-error')),true);assert.equal(posts.filter(p=>p.url.endsWith('/calls')).length,0);
    await page.evaluate(()=>{window.qaDenyMic=false;});await start.click();
    await page.locator('#calling-status').filter({hasText:'Chamando'}).waitFor();
    assert.equal(await page.locator('#calling-slot #calling-name').textContent(),'Isaque');
    await page.waitForFunction(()=>window.qaPeers.at(-1)?.connectionState==='connected');
    assert.equal(await page.locator('#calling-status').textContent(),'Chamando','Transport connected alone must not claim customer accepted');
    call={...call,state:'accepted',version:2};active={...call};
    await page.locator('#calling-status').filter({hasText:'Em ligação'}).waitFor();
    await page.getByRole('button',{name:'Silenciar microfone',exact:true}).click();assert.equal(await page.evaluate(()=>window.qaTracks.at(-1).enabled),false);
    await page.getByRole('button',{name:'Ativar microfone',exact:true}).click();assert.equal(await page.evaluate(()=>window.qaTracks.at(-1).enabled),true);
    const packetStats=await page.evaluate(async()=>{const reports=await window.qaPeers.at(-1).getStats();return [...reports.values()].filter(r=>r.type==='outbound-rtp'||r.type==='inbound-rtp').map(r=>({type:r.type,packets:r.packetsSent||r.packetsReceived}));});
    assert(packetStats.some(s=>s.packets>0));
    convo.messages.push({sender:'cliente',content:'Mensagem fictícia durante ligação'});await page.locator('.thread').getByText('Mensagem fictícia durante ligação',{exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.qaPeers.length),1);
    await page.locator('.nav a[data-route="configuracoes"]').click();await page.locator('body > #calling-bar #calling-status').filter({hasText:'Em ligação'}).waitFor();assert.equal(await page.evaluate(()=>window.qaTracks.at(-1).readyState),'live');
    await page.locator('.nav a[data-route="conversas"]').click();await page.locator('#calling-controls').waitFor();
    fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'desktop-connected.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});await page.locator('.c-item').first().click();
    await page.screenshot({path:path.join(out,'mobile-connected.png'),fullPage:true,animations:'disabled'});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.getByRole('button',{name:'Encerrar chamada',exact:true}).click();await page.locator('#calling-status').filter({hasText:'Chamada encerrada'}).waitFor();
    convo.messages.push({sender:'sistema', event_kind:'whatsapp_call', content:'Ligação pelo WhatsApp por Operadora teste · encerrada · 0:18'});
    await page.locator('.thread .call-event').getByText('Ligação pelo WhatsApp por Operadora teste · encerrada · 0:18').waitFor();
    assert.equal(await page.evaluate(()=>window.qaTracks.every(t=>t.readyState==='ended')&&window.qaPeers.every(p=>p.connectionState==='closed')),true);
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    await start.click();await page.locator('#calling-status').filter({hasText:'Chamando'}).waitFor();await page.getByRole('button',{name:'Cancelar chamada',exact:true}).click();await page.locator('#calling-status').filter({hasText:'Chamada encerrada'}).waitFor();
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    console.log('Calling UI: connection, navigation and cancellation passed');
    await page.evaluate(()=>{window.qaIceFailure=true;});const beforeIce=posts.filter(p=>p.url.endsWith('/calls')).length;
    await start.click();await page.getByRole('alert').filter({hasText:'Não foi possível preparar o áudio'}).waitFor({timeout:15000});assert.equal(posts.filter(p=>p.url.endsWith('/calls')).length,beforeIce);
    assert.equal(await page.evaluate(()=>window.qaTracks.every(t=>t.readyState==='ended')),true);
    await page.evaluate(()=>{window.qaIceFailure=false;});
    uncertain=true;await start.click();await page.locator('#calling-status').filter({hasText:'Chamada encerrada'}).waitFor();
    assert.equal(posts.filter(p=>p.url.endsWith('/calls')).length,beforeIce+1,'Uncertain connect must not be resent');
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    uncertain='http';await start.click();await page.locator('#calling-status').filter({hasText:'Chamada encerrada'}).waitFor();
    assert.equal(posts.filter(p=>p.url.endsWith('/calls')).length,beforeIce+2,'HTTP 500 after acceptance must not create a new operation');
    for(const mode of ['terminal','delayed']){
      await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
      const beforeRecovery=posts.filter(p=>p.url.endsWith('/calls')).length;
      uncertain=mode;
      const firstLookup=mode==='delayed'?page.waitForResponse(response=>response.url().includes('/calls/by-key/')):null;
      await start.click();
      if(firstLookup){
        assert.deepEqual(await (await firstLookup).json(),{call:null});
        assert(await start.isDisabled(),'No reservation yet must not release the uncertain operation');
        assert.equal(await page.locator('#calling-status').textContent(),'Resultado incerto · reconciliando');
      }
      await page.locator('#calling-status').filter({hasText:'Chamada recusada'}).waitFor({timeout:6500});
      assert.equal(await page.locator('#calling-media').textContent(),'Ligação de áudio pelo WhatsApp');
      await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
      assert.equal(posts.filter(p=>p.url.endsWith('/calls')).length,beforeRecovery+1,'Recovery must reuse the original operation without connect');
      assert.equal(await page.evaluate(()=>window.qaTracks.every(t=>t.readyState==='ended')),true);
    }
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    await start.click();await page.locator('#calling-status').filter({hasText:'Chamando'}).waitFor();
    await page.evaluate(()=>{const peer=window.qaPeers.at(-1);Object.defineProperty(peer,'connectionState',{get:()=> 'failed',configurable:true});peer.dispatchEvent(new Event('connectionstatechange'));});
    await page.locator('#calling-status').filter({hasText:'Chamada encerrada'}).waitFor();assert.equal(await page.evaluate(()=>window.qaTracks.every(t=>t.readyState==='ended')),true);
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    await start.click();await page.locator('#calling-status').filter({hasText:'Chamando'}).waitFor();
    const beforeSwitch=posts.length;
    const tenantTermination=page.waitForResponse(response=>response.url().includes('/terminate?tenant=tenant-demo'));
    await page.evaluate(()=>{history.replaceState(null,'','?tenant=tenant-other#conversas');mountCallingControls({id:'other',name:'Outra empresa',channel:'whatsapp'});});
    await page.waitForFunction(()=>document.querySelector('#calling-bar').hidden);assert.equal(await page.evaluate(()=>window.qaTracks.every(t=>t.readyState==='ended')),true);
    await tenantTermination;assert(posts.slice(beforeSwitch).some(p=>p.url.endsWith('/terminate')&&p.tenant==='tenant-demo'));
    active={id:'abandoned',state:'uncertain',active:true,version:1};
    await page.goto(base+'/admin?tenant=tenant-demo#conversas');await page.locator('.c-item').first().click();
    await page.getByText('Chamada em outra aba ou sessão. Aguarde a reconciliação antes de ligar.',{exact:true}).waitFor();assert(await start.isDisabled());assert.equal(await page.evaluate(()=>window.qaPeers.length),0);
    await page.screenshot({path:path.join(out,'mobile-reconciliation.png'),fullPage:true,animations:'disabled'});
    // An older view's in-flight permission response must not redraw another conversation.
    active=null;rootDelay=600;
    await page.evaluate(()=>{mountCallingControls(null);mountCallingControls({id:'conversation-demo',name:'Anterior',channel:'whatsapp'});});
    await page.evaluate(()=>{mountCallingControls(null);document.querySelector('#calling-controls').remove();});
    await page.waitForTimeout(800);assert.equal(await page.locator('#calling-controls').count(),0);rootDelay=0;
    await page.setViewportSize({width:1440,height:1000});await page.reload();
    await page.waitForFunction(()=>document.querySelector('[data-calling="start"]')?.disabled===false);
    await start.click();await page.waitForFunction(()=>window.qaPeers.at(-1)?.connectionState==='connected');
    assert.deepEqual(await page.evaluate(()=>window.qaRejections),[]);
    const logoutResponse=page.waitForResponse(response=>response.url().endsWith('/api/logout'));
    await page.locator('#userBtn').click();await page.locator('#logout').click();await logoutResponse;assert(logoutReleased);
    assert.equal(errors.length,0,errors.join('; '));
    console.log(JSON.stringify({permissionStates:true,ownership:true,realLocalWebRTC:true,packetStats,mute:true,refreshAndNavigation:true,cancel:true,cleanup:true,deniedMicrophone:true,iceTimeout:true,transportFailure:true,uncertainNoRetry:true,lostResponseTerminal:true,reservationNotYetVisible:true,tenantSwitch:true,abandonedSession:true,staleViewIgnored:true,logoutResources:true,escapedHistory:true,mobileNoOverflow:true,screenshots:out}));
  }catch(error){console.error('Calling fixture failure:',error.stack);throw error;}finally{await context.unrouteAll({behavior:'ignoreErrors'});await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
