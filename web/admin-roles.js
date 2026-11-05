async function drawRoleInstructions() {
  const host = $('#cfgBody');
  host.innerHTML = '<section class="card"><div class="card-b">Carregando instruções por papel…</div></section>';
  try {
    const roles = await api('/api/admin/role-instructions');
    if (!host.isConnected || ui.tab !== 'papeis') return;
    host.innerHTML = '<section class="card"><div class="card-h"><h2>Instruções por papel</h2><p>As orientações abaixo complementam a personalidade e as instruções gerais. As permissões das ferramentas são configuradas pela engenharia.</p></div><form class="card-b" id="roleInstructionsForm"><label for="instructionRole">Papel do contato</label><select class="input" id="instructionRole">' + roles.map(r => '<option value="'+esc(r.role)+'">'+esc(r.label)+'</option>').join('') + '</select><label for="roleInstructions" style="display:block;margin-top:20px">Instruções deste papel</label><textarea class="input" id="roleInstructions" maxlength="10000" rows="10"></textarea><div class="savebar"><span id="roleSaved" role="status"></span><button class="btn btn-primary" type="submit">Salvar instruções do papel</button></div></form></section>';
    const select = $('#instructionRole'), text = $('#roleInstructions');
    const fill = () => {text.value = roles.find(r => r.role === select.value)?.instructions || ''; $('#roleSaved').textContent = '';};
    select.onchange = () => {
      const previous = roles.find(r => r.role === select.dataset.previous);
      if (previous) previous.instructions = text.value;
      fill(); select.dataset.previous = select.value;
    };
    select.dataset.previous = select.value; fill();
    $('#roleInstructionsForm').onsubmit = async event => {
      event.preventDefault(); const role=select.value, value=text.value, button=event.submitter;
      button.disabled=true; select.disabled=true;
      try {await api('/api/admin/role-instructions/'+encodeURIComponent(role),'PUT',{instructions:value}); roles.find(r=>r.role===role).instructions=value; $('#roleSaved').textContent='Salvo no banco desta empresa.'; toast('Instruções do papel salvas.');}
      catch(error){toast(error.message);} finally{button.disabled=false;select.disabled=false;}
    };
  } catch(error) {if(host.isConnected)host.textContent=error.message;}
}
