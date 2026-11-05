const commentIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r=".8" fill="currentColor" stroke="none"/></svg>';

function commentEmpty(title, description) {
  return `<section class="card comment-empty"><div class="comment-icon">${commentIcon}</div><h2>${esc(title)}</h2><p>${esc(description)}</p><span class="comment-empty-note">As configurações ficam disponíveis quando um perfil estiver conectado a esta empresa.</span></section>`;
}

async function drawComments() {
  const host = $('#cfgBody');
  host.innerHTML = '<section class="card"><div class="card-b" role="status">Carregando perfis do Instagram…</div></section>';
  try {
    const profiles = await api('/api/admin/instagram/channels');
    if (!host.isConnected || ui.tab !== 'comments') return;
    if (!profiles.length) {
      host.innerHTML = commentEmpty('Seu Instagram, mais perto dos clientes', 'Esta empresa ainda não tem um perfil do Instagram conectado.');
      return;
    }
    host.innerHTML = `<section class="card comment-settings">
      <div class="card-h"><div class="comment-heading"><span class="comment-icon">${commentIcon}</span><div><h2>Comentários do Instagram</h2><p>Defina como a Lumi conversa nas publicações da sua empresa.</p></div></div></div>
      <div class="card-b"><div class="comment-field comment-profile"><label for="commentProfile">Perfil conectado</label><select class="input" id="commentProfile">${profiles.map(p => `<option value="${esc(p.profile_id)}">Perfil · ${esc(p.profile_id)}</option>`).join('')}</select></div>
      <form id="commentForm"><div class="comment-field"><label for="commentInstructions">Instruções para comentários</label><p class="comment-help" id="commentHelp">Oriente o tom e como convidar as pessoas a continuar pelo direct. A personalidade da Lumi também se aplica aqui.</p><textarea class="input" id="commentInstructions" rows="8" maxlength="6000" aria-describedby="commentHelp"></textarea></div>
      <label class="comment-activation" for="commentsEnabled"><span><strong>Respostas automáticas</strong><small>A Lumi responde publicamente aos novos comentários deste perfil.</small></span><input type="checkbox" id="commentsEnabled" role="switch"></label>
      <div class="comment-footer"><p id="commentStatus" role="status" aria-live="polite"></p><button class="btn btn-primary" type="submit">Salvar alterações</button></div></form></div></section>`;
    const profile = $('#commentProfile');
    const form = $('#commentForm');
    const button = form.querySelector('button[type="submit"]');
    async function load() {
      button.disabled = true;
      const id = profile.value;
      const data = await api('/api/admin/instagram/comments/' + id);
      if (!host.isConnected || ui.tab !== 'comments' || profile.value !== id) return;
      $('#commentInstructions').value = data.instructions;
      $('#commentsEnabled').checked = data.enabled;
      $('#commentStatus').textContent = '';
      button.disabled = false;
    }
    profile.onchange = () => load().catch(e => toast(e.message));
    await load();
    form.onsubmit = async e => {
      e.preventDefault();
      button.disabled = true;
      profile.disabled = true;
      const status = $('#commentStatus');
      status.dataset.state = '';
      status.textContent = 'Salvando alterações…';
      try {
        await api('/api/admin/instagram/comments/' + profile.value, 'PUT', {
          enabled: $('#commentsEnabled').checked,
          instructions: $('#commentInstructions').value,
        });
        status.dataset.state = 'saved';
        status.textContent = 'Alterações salvas.';
      } catch (error) {
        status.dataset.state = 'error';
        status.textContent = error.message;
      } finally {
        button.disabled = false;
        profile.disabled = false;
      }
    };
  } catch (error) {
    if (host.isConnected && ui.tab === 'comments') {
      host.innerHTML = `<section class="card"><div class="card-b" role="alert">${esc(error.message)}</div></section>`;
    }
  }
}
