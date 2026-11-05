const form=document.getElementById('form'),statusText=document.getElementById('status'),channel=document.getElementById('channel');
const setupParams=new URLSearchParams(location.search),selectedTenant=setupParams.get('tenant');
const setupUrl=path=>path+(selectedTenant?'?tenant='+encodeURIComponent(selectedTenant):'');
fetch(setupUrl('/api/admin/whatsapp/channels')).then(async response=>{
  if(!response.ok)throw Error('Entre no admin com sua conta e volte a esta página.');
  const channels=await response.json();
  for(const item of channels){const option=document.createElement('option');option.value=item.phone_id;option.textContent='Canal '+item.phone_id;channel.append(option);}
  if(channels.some(item=>item.phone_id===setupParams.get('phone')))channel.value=setupParams.get('phone');
  if(!channels.length){form.hidden=true;statusText.textContent='Esta empresa não tem um canal WhatsApp conectado.';}
}).catch(error=>{form.hidden=true;statusText.textContent=error.message;});
form.onsubmit=async event=>{
  event.preventDefault();const input=document.getElementById('token'),button=document.getElementById('save');button.disabled=true;statusText.textContent='Validando na Meta…';
  try{
    const response=await fetch(setupUrl('/api/admin/whatsapp/token'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone_id:channel.value,token:input.value.trim()})});
    const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Não foi possível conectar.');
    statusText.textContent='Token validado para '+data.phone+'. A ativação do número e o recebimento de mensagens ainda precisam ser conferidos.';
  }catch(error){statusText.textContent=error.message;}finally{input.value='';button.disabled=false;}
};
