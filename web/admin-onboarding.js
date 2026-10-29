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
  openModal(`<section class="card"><div class="card-h"><h2>${field.id ? "Editar" : "Adicionar"} objetivo</h2></div>
    <form id="objectiveForm" class="card-b"><label for="objectiveTitle">Informação a descobrir</label>
    <input class="input" id="objectiveTitle" maxlength="80" required value="${esc(field.title || "")}">
    <label for="objectiveDescription">O que descobrir e quando faz sentido perguntar</label>
    <textarea class="input" id="objectiveDescription" maxlength="2000" required>${esc(field.description || "")}</textarea>
    <p><label><input type="checkbox" id="objectiveRequired" ${field.required !== false ? "checked" : ""}> Obrigatório para concluir o onboarding</label></p>
    <p><label><input type="checkbox" id="objectiveName" ${field.updates_name ? "checked" : ""}> Usar esta informação como nome confirmado do contato</label></p>
    <p>Objetivos orientam a conversa. Não são perguntas fixas e não bloqueiam atendimento humano.</p>
    <div class="actions"><button type="button" class="btn btn-ghost" id="cancelObjective">Cancelar</button><button class="btn btn-primary">Salvar objetivo</button></div></form></section>`);
  $("#cancelObjective").onclick = () => { $("#overlay").hidden = true; };
  $("#objectiveForm").onsubmit = async event => {
    event.preventDefault();
    await api("/api/admin/onboarding" + (field.id ? "/" + field.id : ""), field.id ? "PUT" : "POST", {
      title: $("#objectiveTitle").value.trim(), description: $("#objectiveDescription").value.trim(),
      required: $("#objectiveRequired").checked, updates_name: $("#objectiveName").checked,
    });
    $("#overlay").hidden = true;
    toast("Objetivo salvo no banco da empresa.");
    await drawOnboarding();
  };
}
function renderProfile(profile) {
  if (!profile?.enabled) return "";
  return `<details style="padding:14px;border-bottom:1px solid var(--line)"><summary>Perfil do cliente · ${profile.completed ? "Onboarding concluído" : "Onboarding em andamento"}</summary>
    ${profile.fields.map(f => `<p><strong>${esc(f.title)}</strong>: ${esc(f.value || "Ainda não informado")}</p>`).join("")}</details>`;
}
