let accessRenderVersion=0;
async function renderAccesses(target,fixed,includeRemoved=false){
  const renderVersion=++accessRenderVersion,routeAtStart=location.hash;
  const params=new URLSearchParams();if(fixed)params.set('tenant',fixed);if(includeRemoved)params.set('include_removed','true');
  const users=await api('/api/console/users?'+params),redraw=()=>renderAccesses(target,fixed,includeRemoved);
  if(renderVersion!==accessRenderVersion||location.hash!==routeAtStart||!target.isConnected)return;
  target.innerHTML=(fixed?tenantBack():'')+'<div class="ph"><div><h1>Acessos'+(fixed?' de '+esc(tenant(fixed).name):'')+'</h1><p>Logins, permissões e senhas provisórias.</p></div><button class="btn btn-primary" id="newAccess">Criar acesso</button></div><div class="toolbar"><input class="inp" id="accessSearch" aria-label="Buscar acesso" placeholder="Buscar nome ou e-mail">'+(!fixed?'<select class="sel" id="accessTenantFilter" aria-label="Filtrar empresa" style="max-width:220px"><option value="">Todas as empresas</option><option value="*">Equipe Brevia</option>'+DATA.tenants.map(item=>'<option value="'+item.id+'">'+esc(item.name)+'</option>').join('')+'</select>':'')+'<label class="keep"><input id="includeRemoved" type="checkbox" '+(includeRemoved?'checked':'')+'> Mostrar removidos</label></div><section class="card ut"><div class="rows"><div class="th"><span>Nome</span><span class="h-hide">E-mail</span><span class="h-hide">Empresa</span><span class="h-hide">Perfil</span><span class="h-hide">Situação</span><span>Ações</span></div><div id="accessRows"></div></div></section>';
  const draw=()=>{
    const query=$('#accessSearch').value.toLowerCase(),filter=$('#accessTenantFilter')?.value;
    $('#accessRows').innerHTML=users.filter(user=>(user.name+' '+user.email).toLowerCase().includes(query)&&(!filter||(filter==='*'?user.role==='brevia':user.tenant_id===filter&&user.role!=='brevia'))).map(user=>{
      const status=user.removed?'Removido':!user.enabled?'Desativado':user.must_change_password?'Primeiro acesso':'Ativo';
      return '<div class="tr"><span class="nm"><span><b>'+esc(user.name)+'</b><small>Último acesso: '+esc(date(user.last_login))+'</small></span></span><span class="em hide">'+esc(user.email)+'</span><span class="hide">'+esc(user.role==='brevia'?'Equipe Brevia':tenant(user.tenant_id)?.name||'')+'</span><span class="hide">'+esc({admin:'Administrador',leitura:'Leitura',brevia:'Brevia'}[user.role])+'</span><span class="hide"><span class="pill '+(!user.enabled?'off':user.must_change_password?'warn':'ok')+'">'+status+'</span></span><span class="acts">'+(user.role==='brevia'?'<span class="muted">Conta da equipe</span>':user.removed?'<button class="btn btn-ghost btn-sm" data-restore="'+user.id+'">Restaurar</button>':'<button class="btn btn-ghost btn-sm" data-edit="'+user.id+'">Editar</button><button class="btn btn-ghost btn-sm" data-reset="'+user.id+'">Nova senha</button><button class="btn btn-danger btn-sm" data-remove="'+user.id+'">Remover</button>')+'</span></div>';
    }).join('')||'<div class="empty">Nenhum acesso encontrado.</div>';
    target.querySelectorAll('[data-edit]').forEach(button=>button.onclick=()=>editAccess(users.find(user=>user.id===button.dataset.edit),redraw));
    target.querySelectorAll('[data-reset]').forEach(button=>button.onclick=()=>resetAccess(users.find(user=>user.id===button.dataset.reset),redraw));
    target.querySelectorAll('[data-remove]').forEach(button=>button.onclick=()=>removeAccess(users.find(user=>user.id===button.dataset.remove),redraw));
    target.querySelectorAll('[data-restore]').forEach(button=>button.onclick=async()=>{const user=users.find(user=>user.id===button.dataset.restore);await api('/api/console/users/'+user.id,'PUT',{role:user.role,enabled:true});await redraw();});
  };
  $('#accessSearch').oninput=draw;if($('#accessTenantFilter'))$('#accessTenantFilter').onchange=draw;
  $('#includeRemoved').onchange=event=>renderAccesses(target,fixed,event.target.checked);
  draw();$('#newAccess').onclick=()=>newAccess(fixed,redraw);
}
function credentialModal(user,title){
  const password=user.temporary_password;
  const message='Olá, '+user.name+'! Seu acesso à Lumi está pronto.\nLogin: '+user.email+'\nSenha provisória: '+password+'\nNo primeiro acesso, crie uma senha nova.';
  const close=modal('<h2>'+title+'</h2><p>A senha aparece somente nesta janela. Não será possível consultá-la depois.</p><div class="cred"><div><span>Login</span><code>'+esc(user.email)+'</code></div><div><span>Senha provisória</span><code>'+esc(password)+'</code></div></div><div class="acts"><button class="btn btn-ghost" id="copyCredential">Copiar mensagem</button><button class="btn btn-primary" id="doneCredential">Concluir</button></div>');
  $('#copyCredential').onclick=async()=>{try{await navigator.clipboard.writeText(message);toast('Mensagem copiada');}catch{toast('Não foi possível copiar. Selecione os dados nesta janela.');}};$('#doneCredential').onclick=close;
}
function newAccess(fixed,redraw){
  const close=modal('<form id="accessForm"><h2>Criar acesso</h2><div class="field"><label for="accessName">Nome</label><input class="inp" id="accessName" required maxlength="120"></div><div class="field"><label for="accessEmail">E-mail</label><input class="inp" id="accessEmail" type="email" required></div><div class="field"><label for="accessTenant">Empresa</label><select class="sel" id="accessTenant" '+(fixed?'disabled':'')+'>'+DATA.tenants.map(item=>'<option value="'+item.id+'" '+(fixed===item.id?'selected':'')+'>'+esc(item.name)+'</option>').join('')+'</select></div><div class="field"><label for="accessRole">Perfil</label><select class="sel" id="accessRole"><option value="admin">Administrador do tenant</option><option value="leitura">Somente leitura</option></select></div><p id="accessError" class="errtxt" role="alert"></p><div class="acts"><button class="btn btn-ghost" id="cancelAccess" type="button">Cancelar</button><button class="btn btn-primary" type="submit">Criar acesso</button></div></form>');
  $('#cancelAccess').onclick=close;$('#accessForm').onsubmit=async event=>{
    event.preventDefault();event.submitter.disabled=true;
    try{const user=await api('/api/console/users','POST',{name:$('#accessName').value,email:$('#accessEmail').value,tenant_id:$('#accessTenant').value,role:$('#accessRole').value});close();await redraw();credentialModal(user,'Acesso criado');}
    catch(error){$('#accessError').textContent=error.message;event.submitter.disabled=false;}
  };
}
function editAccess(user,redraw){
  const close=modal('<h2>Editar acesso de '+esc(user.name)+'</h2><div class="field"><label for="editRole">Perfil</label><select class="sel" id="editRole"><option value="admin">Administrador</option><option value="leitura">Somente leitura</option></select></div><label class="keep"><input id="editEnabled" type="checkbox" '+(user.enabled?'checked':'')+'> Acesso ativo</label><p class="muted">A alteração encerra as sessões deste usuário.</p><div class="acts"><button class="btn btn-ghost" id="editCancel">Cancelar</button><button class="btn btn-primary" id="editSave">Salvar</button></div>');
  $('#editRole').value=user.role;$('#editCancel').onclick=close;$('#editSave').onclick=async()=>{await api('/api/console/users/'+user.id,'PUT',{role:$('#editRole').value,enabled:$('#editEnabled').checked});close();await redraw();};
}
function resetAccess(user,redraw){
  const close=modal('<h2>Gerar nova senha?</h2><p>As sessões de '+esc(user.name)+' serão encerradas. A pessoa precisará trocar a senha provisória no próximo acesso.</p><div class="acts"><button class="btn btn-ghost" id="resetCancel">Cancelar</button><button class="btn btn-primary" id="resetConfirm">Gerar senha</button></div>');
  $('#resetCancel').onclick=close;$('#resetConfirm').onclick=async()=>{const changed=await api('/api/console/users/'+user.id+'/password','POST');close();await redraw();credentialModal(changed,'Nova senha provisória');};
}

function removeAccess(user,redraw){
  const close=modal('<h2>Remover acesso de '+esc(user.name)+'?</h2><p>A pessoa perderá o acesso e suas sessões serão encerradas. Conversas e registros anteriores serão preservados. Você poderá restaurar o acesso em “Mostrar removidos”.</p><div class="acts"><button class="btn btn-ghost" id="removeCancel">Cancelar</button><button class="btn btn-danger" id="removeConfirm">Remover acesso</button></div>');
  $('#removeCancel').onclick=close;$('#removeConfirm').onclick=async()=>{await api('/api/console/users/'+user.id,'DELETE');close();await redraw();};
}
