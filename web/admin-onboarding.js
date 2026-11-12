/* Objetivos e perfil usam as classes e os formulários do admin existente. */
async function drawOnboarding() {
  const panel = $("#cfgBody");
  panel.innerHTML = '<section class="card"><div class="card-b">Carregando objetivos…</div></section>';
  const fields = await api("/api/admin/onboarding");
  if (!panel.isConnected || ui.tab !== "onboarding") return;
  panel.innerHTML = `<section class="card"><div class="card-h"><h2>Objetivos do onboarding</h2>
    <p>Defina o que a Lumi precisa descobrir em uma conversa natural. Ela aproveita respostas espontâneas, evita insistência e guarda o perfil para os próximos contatos.</p></div>
    <div class="card-b"><button class="btn btn-primary" id="addObjective">Adicionar objetivo</button>
    ${fields.map(f => `<section class="card" style="margin-top:16px"><div class="card-b"><h3>${esc(f.title)}</h3><p>${esc(f.description)}</p>
      <p>${f.required ? "Obrigatório" : "Opcional"}${f.updates_name ? " · Atualiza o nome confirmado do contato" : ""}</p>
      <button class="btn btn-ghost" data-edit-objective="${f.id}">Editar</button>
      <button class="btn btn-ghost" data-disable-objective="${f.id}">Desativar</button></div></section>`).join("") || "<p>Nenhum objetivo cadastrado. O atendimento segue sem onboarding.</p>"}
    </div></section>`;
  $("#addObjective").onclick = () => objectiveForm();
  panel.querySelectorAll("[data-edit-objective]").forEach(button => {
    button.onclick = () => objectiveForm(fields.find(f => f.id === button.dataset.editObjective));
  });
  panel.querySelectorAll("[data-disable-objective]").forEach(button => {
    button.onclick = async () => {
      if (!confirm("Desativar este objetivo? Os dados já coletados continuarão no banco.")) return;
      await api("/api/admin/onboarding/" + button.dataset.disableObjective, "DELETE");
      await drawOnboarding();
    };
  });
}
function objectiveForm(field = {}) {
  openModal(`<section class="modal onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="objectiveHeading"><header><h2 id="objectiveHeading">${field.id ? "Editar" : "Adicionar"} objetivo</h2><p>Defina uma informação que a Lumi deve descobrir durante o atendimento.</p></header>
    <form id="objectiveForm"><div class="field"><label for="objectiveTitle">Informação a descobrir</label>
    <input class="input" id="objectiveTitle" maxlength="80" required value="${esc(field.title || "")}"></div>
    <div class="field"><label for="objectiveDescription">O que descobrir e quando faz sentido perguntar</label>
    <textarea class="input" id="objectiveDescription" maxlength="2000" required>${esc(field.description || "")}</textarea></div>
    <div class="field"><label for="objectiveChoices">Opções padronizadas (opcional)</label><textarea class="input" id="objectiveChoices" rows="4" placeholder="Opção A | variação A; outra variação">${esc((field.choices||[]).map(c=>c.value+(c.aliases?.length?' | '+c.aliases.join('; '):'')).join('\n'))}</textarea><small>Uma opção por linha. Variações após |, separadas por ponto e vírgula. Vazio mantém texto livre.</small></div>
    <label class="objective-option"><input type="checkbox" id="objectiveAllowOther" ${field.allow_other?'checked':''}><span>Também aceitar informações fora dessas opções</span></label>
    <div class="objective-options"><label class="objective-option"><input type="checkbox" id="objectiveRequired" ${field.required !== false ? "checked" : ""}><span><strong>Informação obrigatória</strong><small>Precisa ser preenchida para concluir o onboarding.</small></span></label>
    <label class="objective-option"><input type="checkbox" id="objectiveName" ${field.updates_name ? "checked" : ""}><span><strong>Usar como nome do contato</strong><small>Atualiza o nome confirmado no perfil do cliente.</small></span></label></div>
    <p class="objective-note">Objetivos orientam uma conversa natural. Não são perguntas fixas e não bloqueiam atendimento humano.</p>
    <div class="objective-actions"><button type="button" class="btn btn-ghost" id="cancelObjective">Cancelar</button><button class="btn btn-primary">Salvar objetivo</button></div></form></section>`);
  $("#cancelObjective").onclick = () => { $("#overlay").hidden = true; };
  $("#objectiveForm").onsubmit = async event => {
    event.preventDefault();
    await api("/api/admin/onboarding" + (field.id ? "/" + field.id : ""), field.id ? "PUT" : "POST", {
      title: $("#objectiveTitle").value.trim(), description: $("#objectiveDescription").value.trim(),
      required: $("#objectiveRequired").checked, updates_name: $("#objectiveName").checked,
      choices: $("#objectiveChoices").value.split('\n').map(line=>line.trim()).filter(Boolean).map(line=>{const [value,...rest]=line.split('|');return {value:value.trim(),aliases:rest.join('|').split(';').map(a=>a.trim()).filter(Boolean)};}),
      allow_other: $("#objectiveAllowOther").checked,
    });
    $("#overlay").hidden = true;
    toast("Objetivo salvo no banco da empresa.");
    await drawOnboarding();
  };
}
