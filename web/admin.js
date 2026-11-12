let me,
  simulationRoles = [],
  contactRoles = [{role:'cliente',label:'Cliente'},{role:'gestor',label:'Gestor'},{role:'atendente',label:'Atendente'}],
  convos = [],
  kb = [],
  imgs = [],
  saved = {},
  draft = {},
  settingsLoaded = false,
  settingsRequest = null,
  lastRows = "",
  refreshing = false;
const ui = {
  conv: "",
  q: "",
  tab: "instrucoes",
  kbq: "",
  imq: "",
  confirm: null,
  confirmImg: null,
  mobileDetail: false,
};
/* ---------------- Utilidades ---------------- */
const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
const chName = (c) => (c === "wa" ? "WhatsApp" : "Instagram");
const nf = (n) => n.toLocaleString("pt-BR");
const today = () => new Date().toLocaleDateString("pt-BR");
const parseD = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const daysBetween = (a, b) => Math.round((parseD(b) - parseD(a)) / 864e5) + 1;
const fmtBR = (s) => {
  const [y, m, d] = s.split("-");
  return d + "/" + m + "/" + y;
};
let toastT;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => (t.hidden = true), 2800);
}
const store = {
  get(k) {
    try {
      return localStorage.getItem(k);
    } catch (e) {
      return null;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch (e) {}
  },
  del(k) {
    try {
      localStorage.removeItem(k);
    } catch (e) {}
  },
};
const chev =
  '<svg class="chev" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 3l4 4-4 4"/></svg>';
const searchIco =
  '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="9" r="5.5"/><path d="M13.5 13.5L17 17" stroke-linecap="round"/></svg>';
function openModal(html) {
  const o = $("#overlay");
  o.innerHTML = html;
  o.hidden = false;
  const close = () => {
    o.hidden = true;
    o.innerHTML = "";
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  document.addEventListener("keydown", onKey);
  o.onmousedown = (e) => {
    if (e.target === o) close();
  };
  return close;
}

function adminPath(path) {
  const tid=new URLSearchParams(location.search).get('tenant');
  if (!tid || !(path.startsWith('/api/admin/') || path==='/api/me')) return path;
  return path+(path.includes('?')?'&':'?')+'tenant='+encodeURIComponent(tid);
}
async function api(path, method = "GET", body) {
  const r = await fetch(adminPath(path), {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Confira os campos informados.",
    );
  return data;
}
window.addEventListener("unhandledrejection", (e) => {
  e.preventDefault();
  toast(e.reason?.message || "Não foi possível salvar.");
});
async function loadKnowledge() {
  kb = (await api("/api/admin/knowledge")).map((k) => ({
    id: k.id,
    t: k.title,
    b: k.content,
    d: "Salvo no banco",
  }));
}
async function loadImages() {
  imgs = (await api("/api/admin/images")).map((i) => ({
    ...i,
    src: adminPath(i.src),
    d: "Salvo no banco",
  }));
}
async function loadSettings() {
  const s = await api("/api/admin/settings");
  saved = {
    tom: s.tone,
    tam: s.length,
    est: s.style,
    instr: s.personality,
    identity: s.identity,
    max_pending: s.max_pending,
    when: "banco de dados",
    by: me.name,
  };
  draft = { ...saved };
  await Promise.all([loadKnowledge(), loadImages()]);
  settingsLoaded = true;
}
function showSettings() {
  if (settingsLoaded) {
    renderCfg();
    return;
  }
  const content = $("#content");
  content.innerHTML = '<div class="cfg"><p role="status">Carregando configurações…</p></div>';
  if (!settingsRequest) {
    settingsRequest = loadSettings().finally(() => { settingsRequest = null; });
  }
  settingsRequest.then(() => {
    if (page() === "configuracoes") renderCfg();
  }).catch(() => {
    if (page() !== "configuracoes") return;
    content.innerHTML = '<div class="cfg"><p role="alert">Não foi possível carregar as configurações.</p><button class="btn btn-ghost" id="retrySettings">Tentar novamente</button></div>';
    $("#retrySettings").onclick = showSettings;
  });
}
async function loadConversationRoles() {
  const results = await Promise.allSettled([
    api('/api/admin/simulations/roles'),
    api('/api/admin/role-instructions'),
  ]);
  if (results[0].status === "fulfilled") simulationRoles = results[0].value;
  if (results[1].status === "fulfilled") contactRoles = results[1].value;
  if (page() === "conversas") {
    lastRows = "";
    refresh();
  }
}
$("#pwToggle").onclick = () => {
  const p = $("#pw");
  p.type = p.type === "password" ? "text" : "password";
  $("#pwToggle").textContent = p.type === "password" ? "Mostrar" : "Ocultar";
};
$("#forgot").onclick = () =>
  toast("Solicite a redefinição de senha à equipe Brevia.");
$("#loginForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/api/login", "POST", {
      email: $("#email").value,
      password: $("#pw").value,
    });
    await boot();
  } catch (e) {
    $("#loginErr").textContent = e.message;
    $("#loginErr").hidden = false;
  }
};
$("#menuBtn").onclick = () => document.body.classList.add("nav-open");
$("#scrim").onclick = () => document.body.classList.remove("nav-open");
const um = $("#userMenu"),
  ub = $("#userBtn");
function closeUserMenu() {
  um.hidden = true;
  ub.setAttribute("aria-expanded", "false");
}
ub.onclick = () => {
  um.hidden = !um.hidden;
  ub.setAttribute("aria-expanded", String(!um.hidden));
};
document.addEventListener("click", (e) => {
  if (!e.target.closest(".user-wrap")) closeUserMenu();
});
$("#logout").onclick = async () => {
  disposeCalling();
  await api("/api/logout", "POST");
  location.reload();
};
document
  .querySelectorAll("[data-support]")
  .forEach((b) => (b.onclick = () => {
    if(!me){toast('Solicite seu acesso à equipe Brevia.');return;}
    const close=openModal('<div class="modal"><h2>Reportar problema</h2><label>Título<input class="input" id="reportTitle" maxlength="160"></label><label>Descrição<textarea class="input" id="reportDescription" maxlength="4000"></textarea></label><p id="reportError" role="alert"></p><button class="btn btn-primary" id="reportSend">Enviar à Brevia</button></div>');
    $('#reportSend').onclick=async()=>{try{await api('/api/admin/problems','POST',{title:$('#reportTitle').value,description:$('#reportDescription').value,priority:'media'});close();toast('Problema registrado para a equipe Brevia.');}catch(error){$('#reportError').textContent=error.message;}};
  }));
window.addEventListener("hashchange", () => {
  if (me) route();
});
document.querySelector('.nav a[data-route="conversas"]').addEventListener('click', () => {
  ui.tp = ''; ui.q = ''; if (page() === 'conversas') renderConvos();
});
async function boot() {
  try {
    me = await api("/api/me");
    if(me.must_change_password || (me.role==='brevia' && !new URLSearchParams(location.search).get('tenant'))){location.replace('/admin');return;}
  } catch {
    me = null;
    $("#login").hidden = false;
    $("#app").hidden = true;
    return;
  }
  $("#login").hidden = true;
  $("#usageNav").hidden=me.role!=="brevia";
  $(".tenant b").textContent = me.tenant;
  $(".tenant .status").textContent=assistantName() + (me.lumi_enabled ? " ativa" : " desativada");
  $(".tenant .status").classList.toggle("off",!me.lumi_enabled);
  $(".tenant .av").textContent = me.tenant.slice(0, 2).toUpperCase();
  paintAccountName();
  route();
  $("#app").hidden = false;
  void loadConversationRoles();
  void refresh();
}
function page() {
  return (location.hash || "#dashboard").slice(1);
}
function route() {
  mountCallingControls(null);
  let p = page();
  if (p !== 'conversas') stopOperatorRecordingUnless(null);
  if(p==="consumo"&&me.role!=="brevia"){p="dashboard";history.replaceState(null,"",location.pathname+location.search+"#dashboard");}
  document.body.classList.remove("nav-open");
  closeUserMenu();
  document
    .querySelectorAll(".nav a")
    .forEach((a) =>
      a.setAttribute("aria-current", a.dataset.route === p ? "page" : "false"),
    );
  $("#pgTitle").textContent =
    {
      dashboard: "Dashboard",
      conversas: "Conversas",
      configuracoes: "Configurações da " + assistantName(),
      consumo: "Consumo e velocidade",
    }[p] || "Dashboard";
  $("#pgSub").textContent =
    me.tenant +
    " · " +
    (p === "conversas"
      ? "Atendimentos e intervenção humana"
      : "Administração da assistente");
  if (p === "consumo") drawUsage();
  else if (p === "configuracoes") showSettings();
  else if (p === "conversas") renderConvos();
  else renderDash();
}
const assistantName = () => me?.assistant_name || 'Lumi';
const statusLabel = (s) =>
  ({
    lumi: assistantName() + " ativa",
    aguardando: "Pediu atendimento humano",
    humano: "Atendimento humano",
  })[s];
function updateHandoverCount() {
  const count = convos.filter((c) => c.status === "aguardando").length;
  const badge = $("#handoverCount");
  badge.textContent = count ? String(count) : "";
  badge.hidden = count === 0;
  badge.setAttribute("aria-label", `${count} ${count === 1 ? "pedido aguardando atendimento humano" : "pedidos aguardando atendimento humano"}`);
}
async function refresh(redraw = true) {
  if (!me || refreshing) return;
  refreshing = true;
  try {
    const data = await api("/api/admin/conversations");
    const changed = JSON.stringify(data) !== lastRows;
    convos = data;
    updateHandoverCount();
    lastRows = JSON.stringify(data);
    if (redraw && changed && !["configuracoes","consumo"].includes(page())) {
      if (page() === "conversas") renderConvos();
      else renderDash();
    }
  } catch (e) {
    toast(e.message);
  } finally {
    refreshing = false;
  }
}
window.addEventListener("DOMContentLoaded", () => { boot(); setInterval(() => refresh(), 1500); });
