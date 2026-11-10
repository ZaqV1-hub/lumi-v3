import {digits,brandOf,BN,fmtNum,V} from './card-fields.js';
import {esc,money,paymentPane,pendingPane,confirmedPane,expiredPane} from './screen.js';
import {authenticateDebit} from './authentication.js';
const $ = id=>document.getElementById(id);
const base=$('checkout').dataset.apiBase || '/checkout/'+$('checkout').dataset.token;
let current,method='pix',busy=false,renderKey='',checking=false;
async function api(path,body) {
  const response=await fetch(base+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  const data=await response.json();
  if(!response.ok)throw Error(data.error || (typeof data.detail==='string'?data.detail:'Não foi possível continuar. Volte à conversa com a Lumi.'));
  return data;
}
const pending = data=>['creating','unknown','pending','issuing_tickets'].includes(data.state);
function notice(text) {const element=$('notice');if(element){element.textContent=text;element.classList.add('status-error');}}
function apply(data,force=false) {
  current=data;$('content').hidden=false;
  $('order').textContent='Seu pedido #'+data.order_id;
  const [year,month,day]=data.quote.visitDate.split('-');$('visit').textContent=`Visita em ${day}/${month}/${year}`;
  $('total').textContent=$('smallTotal').textContent=money(data.quote.totalAmount);
  $('buyer').textContent=data.buyer_name;$('cpf').textContent='CPF '+data.cpf_masked;
  $('items').innerHTML=data.quote.items.map(item=>`<div class="items"><div class="row"><span class="t">${item.quantity} × ${esc(item.title)}</span><b class="num">${money(item.quantity*item.unit_price)}</b></div><div class="m num">${money(item.unit_price)} por ingresso</div></div>`).join('');
  $('environment').textContent=data.sandbox?'Ambiente de testes. Não há cobrança real.':'Este pagamento gera cobrança real na Cielo.';
  $('environment').hidden=data.state==='paid';
  const done=data.state==='paid';
  $('title').textContent=done?'Tudo certo, '+data.buyer_name.split(' ')[0]+'!':'Falta pouco para o seu passeio';
  $('sub').textContent=done?'Seu pagamento foi confirmado.':pending(data)?'Acompanhe a confirmação do pagamento.':'Confira os ingressos e escolha como pagar.';
  $('steps').innerHTML=`<li class="ok"><span class="dot">1</span><span class="tx">Pedido</span></li><span class="bar ok"></span><li class="${done?'ok':'on'}"><span class="dot">2</span><span class="tx">Pagamento</span></li><span class="bar ${done?'ok':''}"></span><li class="${done?'on':''}"><span class="dot">3</span><span class="tx">Confirmação</span></li>`;
  const key=[data.state,data.method,method,Boolean(data.qr_code),Boolean(data.account_url)].join('|');
  if(force || key!==renderKey) {
    renderKey=key;$('paneHost').innerHTML=done?confirmedPane(data):data.state==='expired'?expiredPane():pending(data)?pendingPane(data):paymentPane(data,method);
    if(!done&&!pending(data)&&data.state!=='expired')bindPayment();
    if($('checkPayment'))$('checkPayment').onclick=()=>refresh(true);
    if($('copyPix'))$('copyPix').onclick=async()=>{try{await navigator.clipboard.writeText(current.qr_code);$('copyPix').textContent='Código copiado';}catch{$('pixCode').select();notice('Copie o código selecionado.');}};
    if(['denied','voided','rejected','aborted'].includes(data.state))notice('O pagamento não foi concluído. Confira os dados e tente novamente, ou escolha Pix.');
  }
  countdown();
}
function bindPayment() {
  const tabs=[...document.querySelectorAll('[data-method]')];
  tabs.forEach((tab,index)=>{
    tab.onclick=()=>{if(busy)return;method=tab.dataset.method;apply(current,true);};
    tab.onkeydown=event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const next=(index+(event.key==='ArrowRight'?1:2))%3;method=tabs[next].dataset.method;apply(current,true);document.querySelector(`[data-method="${method}"]`).focus();};
  });
  if($('genPix'))$('genPix').onclick=()=>submitPayment({method:'pix'});
  if(!$('cardForm'))return;
  const fields={number:$('cardNumber'),name:$('cardName'),expiry:$('cardExpiry'),cvv:$('cardCvv')};
  function preview() {
    const n=digits(fields.number.value),brand=brandOf(n);
    $('pvBrand').textContent=BN[brand]||'';$('pvNum').textContent=n?fmtNum(n,brand):'•••• •••• •••• ••••';
    $('pvName').textContent=fields.name.value.toUpperCase()||'SEU NOME';$('pvExp').textContent=fields.expiry.value||'MM/AA';
  }
  fields.number.oninput=()=>{fields.number.value=fmtNum(digits(fields.number.value),brandOf(digits(fields.number.value)));preview();};
  fields.name.oninput=preview;
  fields.expiry.oninput=()=>{const d=digits(fields.expiry.value).slice(0,4);fields.expiry.value=d.length>2?d.slice(0,2)+'/'+d.slice(2):d;preview();};
  fields.cvv.oninput=()=>fields.cvv.value=digits(fields.cvv.value);
  $('cardForm').onsubmit=async event=>{
    event.preventDefault();if(busy)return;
    const brand=brandOf(digits(fields.number.value));
    const errors={number:V.number(fields.number.value),name:V.name(fields.name.value),expiry:V.exp(fields.expiry.value),cvv:V.cvv(fields.cvv.value,brand)};
    if(method==='debit'&&!['visa','master','elo'].includes(brand))errors.number='Para débito, use Visa, Mastercard ou Elo.';
    let first;
    for(const [name,error] of Object.entries(errors)){$(name+'Error').textContent=error;fields[name].setAttribute('aria-invalid',String(Boolean(error)));if(error&&!first)first=fields[name];}
    if(first){first.focus();return;}
    const [month,year]=fields.expiry.value.split('/');
    try {
      await submitPayment({method,holder:fields.name.value.trim(),card_number:digits(fields.number.value),expiration:month+'/20'+year,
        security_code:fields.cvv.value,brand:{visa:'Visa',master:'Master',elo:'Elo',amex:'Amex',hiper:'Hipercard'}[brand],installments:method==='debit'?1:Number($('installments').value)});
    } finally {fields.number.value='';fields.cvv.value='';if($('pvNum'))$('pvNum').textContent='•••• •••• •••• ••••';}
  };
}
async function submitPayment(data) {
  if(busy)return;busy=true;
  const button=$('payButton')||$('genPix');if(button){button.disabled=true;button.textContent=data.method==='debit'?'Confirmando com seu banco…':'Processando…';}
  document.querySelectorAll('[data-method]').forEach(tab=>tab.disabled=true);
  Object.assign(data,{security_token:current.security_token,retry:['denied','voided','aborted','rejected'].includes(current.state)});
  try {
    if(data.method==='debit'&&!current.debit_demo)Object.assign(data,await authenticateDebit(api,data,current));
    const result=await api('/pay',data);apply(result,true);
  } catch(error){notice(error.message);} finally {
    data.card_number='';data.security_code='';data.authentication=null;data.authentication_proof='';busy=false;
    if(button.isConnected){button.disabled=false;button.textContent=method==='pix'?'Gerar Pix de '+money(current.quote.totalAmount):'Pagar '+money(current.quote.totalAmount);}
    document.querySelectorAll('[data-method]').forEach(tab=>tab.disabled=false);
  }
}
async function refresh(manual=false) {
  if(checking||busy)return;checking=true;
  try{apply(await api('/state'));if(manual&&current.state!=='paid')notice('Ainda estamos aguardando a confirmação. A consulta não gera nova cobrança.');}
  catch(error){if(manual)notice(error.message);}finally{checking=false;}
}
function countdown() {
  if(!$('countdown'))return;
  const remaining=Math.max(0,Math.ceil(current.expires_at-Date.now()/1000));
  $('countdown').textContent=remaining?`${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`:'Validade encerrada. Consulte a Lumi para continuar.';
}
const media=matchMedia('(min-width:861px)');const sync=()=>{$('sumD').open=media.matches;};sync();media.addEventListener('change',sync);
api('/state').then(data=>apply(data)).catch(error=>{$('title').textContent='Não foi possível abrir o pedido';$('sub').textContent=error.message;});
setInterval(()=>{if(current&&(pending(current)||current.state==='expired'))refresh();},4000);setInterval(countdown,1000);
