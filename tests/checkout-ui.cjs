// Verificação visual isolada: todas as requisições POST são interceptadas.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
  const url=process.env.CHECKOUT_QA_URL;
  if(!url || new URL(url).hostname!=='127.0.0.1')throw Error('Informe um checkout local de QA');
  const browser=await chromium.launch({headless:true,...(process.env.CHECKOUT_QA_BROWSER?{executablePath:process.env.CHECKOUT_QA_BROWSER}:{})});
  try {
    const page=await browser.newPage({viewport:{width:1400,height:1050}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const response=await page.request.get(url+'/state');
    const fixture=await response.json();
    Object.assign(fixture,{state:'ready',buyer_name:'Prévia de teste',cpf_masked:'***.***.***-00',
      account_url:null,payment_id:null,method:null,qr_code:null,qr_image:null,debit_available:true,expires_at:Date.now()/1000+900});
    let posts=0,debitPayload;
    await page.route('**/*',async route=>{
      const request=route.request();
      if(request.method()!=='GET'){
        posts++;
        if(request.url()===url+'/authenticate')return route.fulfill({json:{access_token:'fake-token',proof:'fake-proof',order_reference:'fake-reference',environment:'PRD',script_url:'https://mpi.braspag.com.br/Scripts/BP.Mpi.3ds20.min.js'}});
        if(request.url()===url+'/pay'){
          const body=request.postDataJSON();
          if(body.method==='debit'){debitPayload=body;return route.fulfill({json:{...fixture,state:'paid',method:'DebitCard'}});}
          return route.fulfill({json:{...fixture,state:'pending',method:'Pix',qr_code:'CODIGO-FICTICIO-APENAS-PARA-QA',qr_image:null}});
        }
        return route.abort();
      }
      if(request.url()==='https://mpi.braspag.com.br/Scripts/BP.Mpi.3ds20.min.js')return route.fulfill({contentType:'application/javascript',body:`window.bpmpi_authenticate=()=>window.bpmpi_config().onSuccess({Cavv:'Y2FyZGluYWw=',Eci:'05',Version:'2.2.0',ReferenceId:'11111111-1111-4111-8111-111111111111'}); window.bpmpi_config().onReady();`});
      if(request.url()===url+'/state')return route.fulfill({json:fixture});
      return route.continue();
    });
    await page.goto(url);await page.getByRole('button',{name:/Gerar Pix/}).waitFor();
    const out=path.join(process.env.LOCALAPPDATA,'Lumi','checkout-qa');fs.mkdirSync(out,{recursive:true});
    await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    await page.getByRole('tab',{name:/Crédito/}).click();
    await page.locator('#cardNumber').fill('123');
    await page.getByRole('button',{name:/Pagar/}).click();
    if(await page.locator('#cardNumber').getAttribute('aria-invalid')!=='true')throw Error('Validação visual ausente');
    if(posts!==0)throw Error('Formulário inválido enviou pagamento');
    await page.getByRole('tab',{name:/Débito/}).click();
    if(await page.locator('#payButton').isDisabled())throw Error('Débito configurado está bloqueado');
    if(await page.locator('#installments').count())throw Error('Débito ofereceu parcelas');
    await page.screenshot({path:path.join(out,'debit.png'),fullPage:true});
    await page.locator('#cardNumber').fill('4111111111111111');
    await page.locator('#cardName').fill('TESTE LOCAL');
    await page.locator('#cardExpiry').fill('12/30');
    await page.locator('#cardCvv').fill('123');
    await page.getByRole('button',{name:/Pagar/}).click();
    await page.getByRole('heading',{name:'Pagamento confirmado'}).waitFor();
    if(debitPayload?.method!=='debit'||debitPayload?.installments!==1||debitPayload?.authentication?.eci!=='05')throw Error('Autenticação de débito não foi encaminhada');
    await page.screenshot({path:path.join(out,'confirmed.png'),fullPage:true});
    await page.goto(url);await page.getByRole('tab',{name:/Pix/}).waitFor();
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('tab',{name:/Pix/}).click();
    await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow)throw Error('Layout tem rolagem horizontal no celular');
    await page.getByRole('button',{name:/Gerar Pix/}).click();
    await page.getByRole('button',{name:/Já paguei/}).waitFor();
    if(await page.locator('#pixCode').inputValue()!=='CODIGO-FICTICIO-APENAS-PARA-QA')throw Error('Código Pix não veio da resposta');
    await page.getByRole('button',{name:/Já paguei/}).click();
    if(posts!==3)throw Error('Consultar pagamento tentou cobrar novamente');
    if(errors.length)throw Error(errors.join('; '));
    console.log(JSON.stringify({desktop:true,mobile:true,creditValidation:true,debit:true,pix:true,realPayments:0,screenshots:out}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
