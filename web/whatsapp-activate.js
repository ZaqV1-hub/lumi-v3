const params=new URLSearchParams(location.search),phone=params.get('phone')||'',tenant=params.get('tenant')||'';
const endpoint='/api/admin/whatsapp/registration/'+encodeURIComponent(phone)+'?tenant='+encodeURIComponent(tenant);
const statusText=document.getElementById('status'),form=document.getElementById('form');
async function refresh(){
  form.hidden=true;
  try{
    const response=await fetch(endpoint),data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Não foi possível consultar.');
    statusText.textContent=(data.display_phone_number||'Número')+' · Status: '+data.status+' · Verificação: '+data.code_verification_status+' · API: '+data.platform_type;
    form.hidden=!(data.code_verification_status==='VERIFIED'&&data.platform_type==='NOT_APPLICABLE');
  }catch(error){statusText.textContent=error.message;}
}
document.getElementById('refresh').onclick=refresh;
form.onsubmit=async event=>{
  event.preventDefault();const input=document.getElementById('pin'),button=document.getElementById('save');button.disabled=true;
  try{
    const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:input.value})});
    const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Falha no registro.');
    form.hidden=true;statusText.textContent=data.message;
  }catch(error){statusText.textContent=error.message;}finally{input.value='';button.disabled=false;}
};
refresh();
