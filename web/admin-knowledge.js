/* Base de conhecimento (texto) */
function drawKb() {
  const q = ui.kbq.toLowerCase();
  const list = kb.filter(
    (k) => !q || k.t.toLowerCase().includes(q) || k.b.toLowerCase().includes(q),
  );
  $("#cfgBody").innerHTML =
    `<div style="display:flex;flex-direction:column;gap:14px">
    <div class="kb-tools"><div class="search">${searchIco}<input class="input" id="kbq" placeholder="Buscar na base de conhecimento" value="${esc(ui.kbq)}"></div><button class="btn btn-primary" id="kbAdd">Adicionar conhecimento</button></div>
    <span class="kb-count num">${list.length} de ${kb.length} blocos</span>
    <div class="kb-grid">${
      list.length
        ? list
            .map(
              (
                k,
              ) => `<article class="card kb"><h3>${esc(k.t)}</h3><p>${esc(k.b)}</p>
      <div class="foot">${ui.confirm === k.id ? `<span class="confirm">Excluir este bloco?</span><div class="acts"><button class="btn btn-ghost btn-sm" data-cancel>Não</button><button class="btn btn-danger btn-sm" data-yes="${k.id}">Excluir</button></div>` : `<small>Atualizado em<br><span class="num">${k.d}</span></small><div class="acts"><button class="btn btn-ghost btn-sm" data-edit="${k.id}">Editar</button><button class="btn btn-danger btn-sm" data-del="${k.id}">Excluir</button></div>`}</div></article>`,
            )
            .join("")
        : `<div class="card empty" style="grid-column:1/-1">Nada encontrado para "${esc(ui.kbq)}".</div>`
    }</div></div>`;
  $("#kbq").oninput = (e) => {
    ui.kbq = e.target.value;
    const p = e.target.selectionStart;
    drawKb();
    const n = $("#kbq");
    n.focus();
    n.setSelectionRange(p, p);
  };
  $("#kbAdd").onclick = () => kbModal();
  const b = $("#cfgBody");
  b.querySelectorAll("[data-edit]").forEach(
    (x) => (x.onclick = () => kbModal(kb.find((k) => k.id === x.dataset.edit))),
  );
  b.querySelectorAll("[data-del]").forEach(
    (x) =>
      (x.onclick = () => {
        ui.confirm = x.dataset.del;
        drawKb();
      }),
  );
  b.querySelectorAll("[data-cancel]").forEach(
    (x) =>
      (x.onclick = () => {
        ui.confirm = null;
        drawKb();
      }),
  );
  b.querySelectorAll("[data-yes]").forEach(
    (x) =>
      (x.onclick = async () => {
        await api("/api/admin/knowledge/" + x.dataset.yes, "DELETE");
        await loadKnowledge();
        ui.confirm = null;
        drawKb();
        toast("Bloco excluído");
      }),
  );
}
function kbModal(item) {
  const close =
    openModal(`<form class="modal" id="kbForm" role="dialog" aria-modal="true" aria-labelledby="kbTitle">
    <h2 id="kbTitle">${item ? "Editar conhecimento" : "Novo conhecimento"}</h2>
    <div class="field"><label for="kbT">Título</label><input class="input" id="kbT" placeholder="Ex.: Regras para pets"></div>
    <div class="field"><label for="kbB">Conteúdo</label><textarea class="input" id="kbB" style="min-height:160px" placeholder="Escreva como você explicaria para um atendente novo."></textarea></div>
    <p class="err" id="kbErr" hidden>Preencha o título e o conteúdo para salvar.</p>
    <div class="acts"><button type="button" class="btn btn-ghost" id="kbCancel">Cancelar</button><button class="btn btn-primary" type="submit">${item ? "Salvar" : "Adicionar"}</button></div></form>`);
  if (item) {
    $("#kbT").value = item.t;
    $("#kbB").value = item.b;
  }
  $("#kbT").focus();
  $("#kbCancel").onclick = close;
  $("#kbForm").onsubmit = async (e) => {
    e.preventDefault();
    const t = $("#kbT").value.trim(),
      b = $("#kbB").value.trim();
    if (!t || !b) {
      $("#kbErr").hidden = false;
      return;
    }
    await api(
      "/api/admin/knowledge" + (item ? "/" + item.id : ""),
      item ? "PUT" : "POST",
      { title: t, content: b },
    );
    await loadKnowledge();
    close();
    drawKb();
    toast(item ? "Bloco atualizado" : "Conhecimento adicionado");
  };
}
