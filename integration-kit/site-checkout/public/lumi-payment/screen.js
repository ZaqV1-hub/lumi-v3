import {I} from './card-fields.js';
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const methodLabel = value => ({Pix:'Pix',CreditCard:'Cartão de crédito',DebitCard:'Cartão de débito'}[value] || 'Pagamento online');

function paymentPane(data, method) {
  const pix = method === 'pix', debit = method === 'debit', unavailable = debit && !data.debit_available;
  return `<section class="card pane" aria-labelledby="paymentTitle"><h2 id="paymentTitle">Forma de pagamento</h2>
    <div class="tabs" role="tablist" aria-label="Forma de pagamento">
    ${[['pix','Pix','Pague pelo app do banco'],['card','Crédito','À vista ou parcelado'],['debit','Débito','À vista, com autenticação']].map(([value,label,hint])=>
      `<button type="button" class="tab" role="tab" data-method="${value}" aria-selected="${method===value}" aria-controls="paymentPanel" tabindex="${method===value?0:-1}">${label}<small>${hint}</small></button>`).join('')}</div>
    <div class="tabpanel" id="paymentPanel" role="tabpanel">
    ${pix ? `<p class="lead">Pague com Pix pelo aplicativo do seu banco.</p><ul class="perks"><li>${I.ok}<span>Confira o valor e confirme o pagamento no seu banco.</span></li><li>${I.ok}<span>Esta tela acompanha a confirmação automaticamente.</span></li></ul><button class="btn btn-primary btn-block" id="genPix">Gerar Pix de ${money(data.quote.totalAmount)}</button><p class="fine">${I.clock}<span>A validade será exibida após gerar o código.</span></p>` :
      `${unavailable ? `<div class="notice info">${I.lock}<div><b>Cartão de débito</b>O débito ainda aguarda a configuração da autenticação do banco. Por enquanto, escolha Pix ou crédito.</div></div>` : ''}
      <div class="cardprev" aria-hidden="true"><div class="top"><span class="chip"></span><span class="br" id="pvBrand"></span></div><div class="nb num" id="pvNum">•••• •••• •••• ••••</div><div class="bt"><div><small>Nome</small><b id="pvName">SEU NOME</b></div><div><small>Validade</small><b id="pvExp">MM/AA</b></div></div></div>
      <form class="form" id="cardForm" novalidate>
      <div class="f full"><label for="cardNumber">Número do cartão</label><div class="inp"><input id="cardNumber" inputmode="numeric" autocomplete="cc-number" placeholder="0000 0000 0000 0000" maxlength="23" aria-describedby="numberError" ${unavailable?'disabled':''}></div><div class="err" id="numberError" role="alert"></div></div>
      <div class="f full"><label for="cardName">Nome impresso no cartão</label><div class="inp"><input id="cardName" autocomplete="cc-name" placeholder="Como está no cartão" maxlength="120" aria-describedby="nameError" ${unavailable?'disabled':''}></div><div class="err" id="nameError" role="alert"></div></div>
      <div class="f"><label for="cardExpiry">Validade</label><div class="inp"><input id="cardExpiry" inputmode="numeric" autocomplete="cc-exp" placeholder="MM/AA" maxlength="5" aria-describedby="expiryError" ${unavailable?'disabled':''}></div><div class="err" id="expiryError" role="alert"></div></div>
      <div class="f"><label for="cardCvv">Código de segurança</label><div class="inp"><input id="cardCvv" type="password" inputmode="numeric" autocomplete="cc-csc" placeholder="CVV" maxlength="4" aria-describedby="cvvError" ${unavailable?'disabled':''}></div><div class="err" id="cvvError" role="alert"></div></div>
      ${debit?'':`<div class="f full"><label for="installments">Parcelas</label><select id="installments">${Array.from({length:data.max_installments},(_,i)=>`<option value="${i+1}">${i+1}x de ${money(data.quote.totalAmount/(i+1))}</option>`).join('')}</select></div>`}
      <div class="f full"><button class="btn btn-primary btn-block" type="submit" id="payButton" ${unavailable?'disabled':''}>${unavailable?'Débito ainda indisponível':'Pagar '+money(data.quote.totalAmount)}</button></div></form>
      <p class="fine">${I.lock}<span>Pagamento processado pela Cielo. Os dados do cartão não são armazenados.</span></p>`}
    <div id="notice" class="error-copy" role="status" aria-live="polite"></div></div></section>`;
}

function pendingPane(data) {
  const pix = data.method === 'Pix';
  const image = data.qr_image || '';
  const qr = /^[A-Za-z0-9+/=\r\n]+$/.test(image) ? `<img src="data:image/png;base64,${image.replace(/[\r\n]/g,'')}" alt="QR Code Pix">` : '<span>Use o código Pix copia e cola</span>';
  return `<section class="card pane"><div class="pix-head"><h2>${pix?'Pague com Pix':'Verificando pagamento'}</h2><span class="pill wait">Aguardando</span></div>
    ${pix && data.qr_code ? `<div class="pix-body"><div><div class="qr">${qr}</div><p class="qrcap">Aponte a câmera do app do seu banco</p></div><div class="side"><ol class="how"><li><i>1</i><span>Abra o app do banco e escolha Pix.</span></li><li><i>2</i><span>Leia o QR Code ou copie o código abaixo.</span></li><li><i>3</i><span>Confira o valor de <b>${money(data.quote.totalAmount)}</b> e confirme.</span></li></ol><div class="copy"><label class="lbl" for="pixCode">Pix copia e cola</label><div class="cr"><input id="pixCode" readonly value="${esc(data.qr_code)}"><button class="btn btn-primary" id="copyPix">${I.copy}Copiar código</button></div></div></div></div><p class="fine">Validade restante: <span class="num" id="countdown"></span></p>`:''}
    <div class="watch" role="status"><span class="spin"></span><div><b>${data.state==='issuing_tickets'?'Preparando seus ingressos':'Acompanhando a confirmação'}</b>${data.state==='issuing_tickets'?'O pagamento foi recebido. Aguarde o registro dos ingressos.':'Assim que o pagamento for confirmado, esta tela será atualizada.'}</div></div><div class="pix-act"><button class="btn btn-ghost" id="checkPayment">${pix?'Já paguei':'Consultar pagamento'}</button></div><p id="notice" class="fine" role="status"></p></section>`;
}

function confirmedPane(data) {
  const quantity = data.quote.items.reduce((total,item)=>total+item.quantity,0);
  return `<section class="card pane"><div class="center"><span class="ico ok">${I.big}</span><h2>Pagamento confirmado</h2><p>Seus ${quantity} ingressos estão registrados no sistema de ingressos e vinculados ao CPF da compra.</p></div>
    <dl class="receipt"><div class="r"><dt>Valor pago</dt><dd>${money(data.quote.totalAmount)}</dd></div><div class="r"><dt>Forma de pagamento</dt><dd>${esc(methodLabel(data.method))}</dd></div><div class="r"><dt>Pedido</dt><dd>#${esc(data.order_id)}</dd></div>${data.payment_id?`<div class="r"><dt>Transação</dt><dd>${esc(data.payment_id)}</dd></div>`:''}</dl>
    <div class="tickets">${data.quote.items.map(item=>`<div class="tk"><div><b>${item.quantity} × ${esc(item.title)}</b><span>Vinculado ao CPF ${esc(data.cpf_masked)}</span></div></div>`).join('')}</div>
    ${data.account_url?`<div class="actions"><a class="btn btn-primary" href="${esc(data.account_url)}" rel="noreferrer">Concluir meu cadastro</a></div>`:''}<p class="fine">Você pode voltar à conversa com a Lumi para continuar o atendimento.</p></section>`;
}

function expiredPane() {
  return `<section class="card pane"><div class="center"><span class="ico warn">${I.clock}</span><h2>Este link expirou</h2><p>Volte à conversa com a Lumi para consultar um pagamento já feito ou solicitar uma nova cotação.</p><div class="actions"><button class="btn btn-ghost" id="checkPayment">Consultar pagamento</button></div></div><p class="fine" id="notice" role="status"></p></section>`;
}

export {esc,money,paymentPane,pendingPane,confirmedPane,expiredPane};
