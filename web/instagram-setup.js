const form=document.getElementById('form'),statusText=document.getElementById('status'),channel=document.getElementById('channel');
const params=new URLSearchParams(location.search),tenant=params.get('tenant');
const setupUrl=path=>path+(tenant?'?tenant='+encodeURIComponent(tenant):'');
fetch(setupUrl('/api/admin/instagram/channels')).then(async response=>{
  if(!response.ok)throw Error('Entre no admin com sua conta e volte a esta página.');
  const channels=await response.json();
  for(const item of channels){const option=document.createElement('option');option.value=item.profile_id;option.textContent='Perfil '+item.profile_id;channel.append(option);}
  if(channels.some(item=>item.profile_id===params.get('profile')))channel.value=params.get('profile');
  if(!channels.length){form.hidden=true;statusText.textContent='Esta empresa não tem perfil Instagram configurado.';}
}).catch(error=>{form.hidden=true;statusText.textContent=error.message;});
form.onsubmit=async event=>{
  event.preventDefault();const input=document.getElementById('token'),button=document.getElementById('save');button.disabled=true;statusText.textContent='Validando na Meta…';
  try{
    const response=await fetch(setupUrl('/api/admin/instagram/token'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:channel.value,token:input.value.trim()})});
    const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Não foi possível validar.');
    statusText.textContent='Token validado para @'+data.username+'. O recebimento e a resposta de mensagens ainda precisam ser testados.';
  }catch(error){statusText.textContent=error.message;}finally{input.value='';button.disabled=false;}
};
