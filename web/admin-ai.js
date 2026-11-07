async function drawAi() {
  if (me.role !== 'brevia') return;
  const host = $('#cfgBody');
  host.innerHTML = '<section class="card"><div class="card-b" role="status">Carregando configuração de IA…</div></section>';
  try {
    let savedAi = await api('/api/admin/ai');
    if (!host.isConnected || ui.tab !== 'ai') return;
    host.innerHTML = `<section class="card">
      <div class="card-h"><h2>Inteligência artificial</h2><p>Escolha a IA utilizada por ${esc(me.tenant)}. A configuração vale somente para esta empresa.</p></div>
      <form class="card-b" id="aiForm" autocomplete="off" style="display:flex;flex-direction:column;gap:18px">
        <div class="field"><label for="aiProvider">Provedor</label><select class="input" id="aiProvider" required>
          <option value="">Selecione uma opção</option>
          <option value="codex">Codex local (neste servidor)</option>
          <option value="codex_gateway">Codex pelo gateway</option>
          <option value="openai">OpenAI API</option>
          <option value="demo">Demonstração (sem IA)</option>
        </select></div>
        <div class="field" id="aiModelField"><label for="aiModel">Modelo</label><input class="input" id="aiModel" maxlength="100" autocomplete="off" spellcheck="false"><p class="opt-hint" id="aiProviderHelp"></p></div>
        <div id="aiCredentials">
          <div class="field" id="aiKeyField"><label for="aiKey">Nova chave OpenAI</label><input class="input" id="aiKey" type="password" maxlength="4096" autocomplete="off" spellcheck="false" aria-describedby="aiKeyHelp"><p class="opt-hint" id="aiKeyHelp">Deixe em branco para manter a chave cadastrada. A chave não será exibida depois de salvar.</p></div>
          <p id="aiKeyStatus" role="status"></p>
          <label class="check" id="aiRemoveField"><input type="checkbox" id="aiRemoveKey"> Remover a chave OpenAI desta empresa</label>
        </div>
        <p id="aiSavedState" role="status"></p>
        <div class="savebar"><span id="aiStatus" role="status" aria-live="polite"></span><button class="btn btn-primary" type="submit">Salvar configuração de IA</button></div>
      </form></section>`;
    const form = host.querySelector('#aiForm');
    const provider = host.querySelector('#aiProvider');
    const model = host.querySelector('#aiModel');
    const key = host.querySelector('#aiKey');
    const remove = host.querySelector('#aiRemoveKey');
    const status = host.querySelector('#aiStatus');
    const helps = {
      codex: 'Use um modelo disponível na sessão Codex deste servidor.',
      codex_gateway: 'Use um modelo permitido pelo gateway Codex configurado neste ambiente.',
      openai: 'Use um modelo disponível no projeto OpenAI desta empresa e compatível com respostas estruturadas.',
    };
    function sync() {
      const isApi = provider.value === 'openai';
      const needsModel = !!provider.value && provider.value !== 'demo';
      host.querySelector('#aiModelField').hidden = !needsModel;
      model.required = needsModel;
      host.querySelector('#aiProviderHelp').textContent = helps[provider.value] || '';
      host.querySelector('#aiCredentials').hidden = !isApi && !savedAi.api_key_configured;
      host.querySelector('#aiKeyField').hidden = !isApi;
      key.disabled = !isApi;
      host.querySelector('#aiRemoveField').hidden = !savedAi.api_key_configured;
      host.querySelector('#aiKeyStatus').textContent = savedAi.api_key_configured ? 'Chave OpenAI cadastrada para esta empresa.' : 'Nenhuma chave OpenAI cadastrada para esta empresa.';
      host.querySelector('#aiSavedState').textContent = !savedAi.provider
        ? 'Esta empresa ainda não tem uma IA configurada.'
        : savedAi.ready ? 'Configuração completa. A disponibilidade do modelo é confirmada ao conversar.' : 'A configuração salva ainda precisa ser completada antes de responder.';
    }
    provider.value = savedAi.provider || '';
    model.value = savedAi.model || '';
    provider.onchange = () => {
      key.value = '';
      remove.checked = false;
      model.value = provider.value === savedAi.provider ? savedAi.model || '' : '';
      status.textContent = 'Alterações ainda não salvas.';
      sync();
    };
    key.oninput = () => { if (key.value) remove.checked = false; };
    remove.onchange = () => { if (remove.checked) key.value = ''; };
    form.onsubmit = async event => {
      event.preventDefault();
      const data = {provider: provider.value, model: provider.value === 'demo' ? '' : model.value.trim(), remove_api_key: remove.checked};
      if (key.value.trim()) data.api_key = key.value.trim();
      key.value = '';
      const controls = [...form.querySelectorAll('input,select,button')];
      controls.forEach(control => { control.disabled = true; });
      status.textContent = 'Salvando configuração…';
      try {
        savedAi = await api('/api/admin/ai', 'PUT', data);
        if (!host.isConnected || ui.tab !== 'ai') return;
        provider.value = savedAi.provider || '';
        model.value = savedAi.model || '';
        remove.checked = false;
        status.textContent = 'Configuração de IA salva para esta empresa.';
      } catch {
        status.textContent = 'Não foi possível salvar. Confira o modelo e a configuração de credenciais. Se informou uma nova chave, digite-a novamente.';
      } finally {
        delete data.api_key;
        controls.forEach(control => { control.disabled = false; });
        sync();
      }
    };
    sync();
  } catch {
    if (host.isConnected && ui.tab === 'ai') {
      host.innerHTML = '<section class="card"><div class="card-b" role="alert">Não foi possível carregar a configuração de IA desta empresa.</div></section>';
    }
  }
}
