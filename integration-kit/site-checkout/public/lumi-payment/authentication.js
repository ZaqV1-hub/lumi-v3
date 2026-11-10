// MPI V2 do site Rincão: o script atual é carregado diretamente da Cielo.
export async function authenticateDebit(api, data, order) {
  const session = await api('/authenticate', data);
  const container = document.createElement('div');
  container.hidden = true;
  const [month,year] = data.expiration.split('/');
  const values = {auth:'true',auth_notifyonly:'false',accesstoken:session.access_token,
    ordernumber:session.order_reference,currency:'986',totalamount:String(Math.round(order.quote.totalAmount*100)),
    installments:'1',paymentmethod:'debit',cardnumber:data.card_number,
    cardexpirationmonth:month,cardexpirationyear:year,cardholdername:data.holder};
  for (const [name,value] of Object.entries(values)) {
    const input=document.createElement('input');input.type='hidden';input.className='bpmpi_'+name;input.value=value;container.append(input);
  }
  document.body.append(container);
  let script;
  try {
    const result = await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('A autenticação do banco expirou. Tente novamente.')),120000);
      const finish=(fn,value)=>{clearTimeout(timer);fn(value);};
      const failure=()=>finish(reject,Error('O banco não confirmou a autenticação. Tente outro cartão ou use Pix.'));
      window.bpmpi_config=()=>({Environment:session.environment,Debug:false,
        onReady:()=>window.bpmpi_authenticate(),
        onSuccess:result=>finish(resolve,result),
        onFailure:failure,onUnenrolled:failure,onDisabled:failure,onError:failure,onUnsupportedBrand:failure});
      script=document.createElement('script');script.src=session.script_url;script.onerror=failure;document.head.append(script);
    });
    return {authentication_proof:session.proof,authentication:{cavv:result.Cavv,eci:result.Eci,
      version:result.Version,reference_id:result.ReferenceId,xid:result.Xid || null}};
  } finally {
    container.querySelectorAll('input').forEach(input=>input.value='');container.remove();script?.remove();
    window.bpmpi_config=()=>({Environment:session.environment,Debug:false});
  }
}
