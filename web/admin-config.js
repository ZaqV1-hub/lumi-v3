/* ---------------- Configurações ---------------- */
function renderCfg() {
  const tabs = [
    ["instrucoes", "Instruções"],
    ["kb", "Base de conhecimento"],
    ["imgs", "Imagens"],
  ];
  $("#content").innerHTML =
    `<div class="cfg ${ui.tab === "imgs" ? "wide" : ""}">
    <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-selected="${ui.tab === k}">${l}</button>`).join("")}</div>
    <div id="cfgBody"></div></div>`;
  $("#content")
    .querySelectorAll(".tabs [data-tab]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          ui.tab = b.dataset.tab;
          renderCfg();
        }),
    );
  ({ instrucoes: drawInstr, kb: drawKb, imgs: drawImgs })[ui.tab]();
}
const dirty = () =>
  draft.identity !== saved.identity ||
  draft.greeting !== saved.greeting ||
  draft.max_pending !== saved.max_pending ||
  draft.tom !== saved.tom ||
  draft.tam !== saved.tam ||
  draft.est !== saved.est ||
  draft.instr !== saved.instr;
const hints = {
  Alegre: "Próxima e animada, com exclamações na medida.",
  Neutro: "Cordial e direta, sem entusiasmo extra.",
  Formal: "Tratamento mais sóbrio, sem gírias.",
  Curto: "Uma ou duas frases por resposta.",
  Médio: "Até um parágrafo curto, com o essencial.",
  Detalhado: "Explica com mais contexto quando o assunto pede.",
  Objetivo: "Responde o que foi perguntado e oferece o próximo passo.",
  Explicativo: "Explica o porquê das regras e dá exemplos.",
};
function optGroup(key, label, vals) {
  return `<div class="opt-group"><span class="lbl">${label}</span><div class="opts">${vals.map((v) => `<button class="opt" data-k="${key}" data-v="${v}" aria-pressed="${draft[key] === v}">${v}</button>`).join("")}</div><p class="opt-hint">${hints[draft[key]]}</p></div>`;
}
function drawInstr() {
  $("#cfgBody").innerHTML =
    `<div style="display:flex;flex-direction:column;gap:18px">
    <section class="card"><div class="card-h"><h2>Personalidade da Lumi</h2><p>Defina como a Lumi conversa com os clientes da sua empresa.</p></div>
      <div class="card-b">${optGroup("tom", "Tom", ["Alegre", "Neutro", "Formal"])}${optGroup("tam", "Tamanho das respostas", ["Curto", "Médio", "Detalhado"])}${optGroup("est", "Estilo", ["Objetivo", "Explicativo"])}</div></section>
    <section class="card"><div class="card-h"><h2>Identidade da Lumi</h2></div><div class="card-b"><textarea class="input" id="identity">${esc(draft.identity)}</textarea></div></section><section class="card"><div class="card-h"><h2>Saudação rápida</h2><p>Resposta imediata para Oi, Olá e saudações simples. Use {nome} ou {empresa} para personalizar. Deixe vazio para a Lumi criar a resposta.</p></div><div class="card-b"><textarea class="input" id="greeting" maxlength="1000">${esc(draft.greeting)}</textarea></div></section><section class="card"><div class="card-h"><h2>Anti-spam</h2><p>Mensagens em andamento antes dos avisos e do bloqueio.</p></div><div class="card-b"><label for="maxPending">Limite de mensagens</label><input class="input" type="number" id="maxPending" min="1" max="10" value="${draft.max_pending}"><p>Após atingir o limite: aviso para aguardar, aviso de bloqueio e bloqueio persistente. O desbloqueio fica na conversa.</p></div></section><section class="card"><div class="card-h"><h2>Instruções livres</h2><p>Uma instrução por linha.</p></div>
      <div class="card-b"><textarea class="input" id="instr" aria-label="Instruções livres">${esc(draft.instr)}</textarea>
      <div class="note"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1" stroke-linecap="round"/></svg>Essas instruções complementam as regras fixas da Lumi e não substituem as regras de segurança da plataforma.</div></div></section>
    <div class="savebar"><span class="last" id="lastSaved"></span><div class="actions"><button class="btn btn-ghost" id="discard">Descartar</button><button class="btn btn-primary" id="save">Salvar alterações</button></div></div>
  </div>`;
  const sync = () => {
    const d = dirty();
    const l = $("#lastSaved");
    l.textContent = d
      ? "Você tem alterações não salvas"
      : `Última alteração em ${saved.when} por ${saved.by}`;
    l.classList.toggle("dirty", d);
    $("#save").disabled = !d;
    $("#discard").disabled = !d;
  };
  $("#cfgBody")
    .querySelectorAll(".opt")
    .forEach(
      (b) =>
        (b.onclick = () => {
          draft[b.dataset.k] = b.dataset.v;
          const y = $("#content").scrollTop;
          drawInstr();
          $("#content").scrollTop = y;
        }),
    );
  $("#greeting").oninput = (e) => {draft.greeting = e.target.value; sync();};
  $("#identity").oninput = (e) => {
    draft.identity = e.target.value;
    sync();
  };
  $("#maxPending").oninput = (e) => {
    draft.max_pending = Number(e.target.value);
    sync();
  };
  $("#instr").oninput = (e) => {
    draft.instr = e.target.value;
    sync();
  };
  $("#discard").onclick = () => {
    draft = { ...saved };
    drawInstr();
    toast("Alterações descartadas");
  };
  $("#save").onclick = async () => {
    await api("/api/admin/settings", "PUT", {
      identity: draft.identity,
      greeting: draft.greeting,
      personality: draft.instr,
      tone: draft.tom,
      length: draft.tam,
      style: draft.est,
      max_pending: draft.max_pending,
    });
    Object.assign(saved, draft, { when: today(), by: me.name });
    draft = { ...saved };
    sync();
    toast("Configurações salvas.");
  };
  sync();
}
