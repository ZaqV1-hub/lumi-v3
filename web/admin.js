let me,
  convos = [],
  kb = [],
  imgs = [],
  saved = {},
  draft = {},
  settingsLoaded = false,
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

async function api(path, method = "GET", body) {
  const r = await fetch(path, {
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
$("#pwToggle").onclick = () => {
  const p = $("#pw");
  p.type = p.type === "password" ? "text" : "password";
  $("#pwToggle").textContent = p.type === "password" ? "Mostrar" : "Ocultar";
};
$("#forgot").onclick = () =>
  toast("Neste ambiente de teste, use a senha demo1234.");
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
  await api("/api/logout", "POST");
  location.reload();
};
document
  .querySelectorAll("[data-support]")
  .forEach((b) => (b.onclick = () => toast("Ambiente local de teste.")));
window.addEventListener("hashchange", () => {
  if (me) route();
});
document.querySelector('.nav a[data-route="conversas"]').addEventListener('click', () => {
  ui.tp = ''; ui.q = ''; if (page() === 'conversas') renderConvos();
});
async function boot() {
  try {
    me = await api("/api/me");
  } catch {
    me = null;
    $("#login").hidden = false;
    $("#app").hidden = true;
    return;
  }
  $("#login").hidden = true;
  $("#app").hidden = false;
  $(".tenant b").textContent = me.tenant;
  $(".tenant .av").textContent = me.tenant.slice(0, 2).toUpperCase();
  $("#userBtn .name").textContent = me.name;
  $("#userBtn .av").textContent = me.name[0];
  $(".um-id b").textContent = me.name + " · " + me.tenant;
  $(".um-id span").textContent = "";
  await loadSettings();
  await refresh(false);
  route();
}
function page() {
  return (location.hash || "#dashboard").slice(1);
}
function route() {
  const p = page();
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
      configuracoes: "Configurações da Lumi",
    }[p] || "Dashboard";
  $("#pgSub").textContent =
    me.tenant +
    " · " +
    (p === "conversas"
      ? "Atendimentos e intervenção humana"
      : "Administração da assistente");
  if (p === "configuracoes") renderCfg();
  else if (p === "conversas") renderConvos();
  else renderDash();
}
const statusLabel = (s) =>
  ({
    lumi: "Lumi ativa",
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
    if (redraw && changed && page() !== "configuracoes") {
      if (page() === "conversas") {
        const draftText = $("#humanText")?.value || "";
        const focus = document.activeElement?.id;
        renderConvos();
        if ($("#humanText")) {
          $("#humanText").value = draftText;
          if (focus === "humanText") $("#humanText").focus();
        }
      } else renderDash();
    }
  } catch (e) {
    toast(e.message);
  } finally {
    refreshing = false;
  }
}
function renderConvos() {
  const text = $("#humanText")?.value || "";
  const waiting = convos.filter((c) => c.status === "aguardando");
  $("#content").innerHTML =
    '<div class="wrap">' +
    (waiting.length
      ? '<div class="notice-live" role="status">' +
        waiting
          .map((c) => esc(c.name) + " pediu atendimento humano.")
          .join(" ") +
        "</div>"
      : "") +
    '<div class="filters"><div class="search">' +
    searchIco +
    '<input class="input" id="cq" placeholder="Buscar por nome" value="' +
    esc(ui.q) +
    '"></div></div><div id="cbody"></div></div>';
  $("#cq").oninput = (e) => {
    ui.q = e.target.value;
    drawConvoBody();
  };
  drawConvoBody();
  if ($("#humanText")) $("#humanText").value = text;
}
function drawConvoBody() {
  const selectedStatus = { 'Lumi ativa': 'lumi', 'Aguardando atendimento': 'aguardando', 'Atendimento humano': 'humano' }[ui.tp];
  const list = convos.filter((c) =>
    c.name.toLowerCase().includes(ui.q.toLowerCase()) && (!selectedStatus || c.status === selectedStatus),
  );
  if (!list.some((c) => c.id === ui.conv)) ui.conv = list[0]?.id || "";
  const c = list.find((c) => c.id === ui.conv);
  $("#cbody").innerHTML =
    '<section class="card convo ' +
    (ui.mobileDetail && c ? "show-detail" : "") +
    '"><div class="c-list"><div class="count">' +
    list.length +
    ' atendimentos</div><div class="c-items">' +
    list
      .map(
        (c) =>
          '<button class="c-item" data-id="' +
          c.id +
          '" aria-current="' +
          (c.id === ui.conv) +
          '"><span class="top"><span class="pill wa">' + (c.channel === 'whatsapp' ? 'WhatsApp' : 'Simulador') + '</span></span><b>' +
          esc(c.name) +
          '</b><span class="last">' +
          esc(c.messages.at(-1)?.content || "Conversa iniciada") +
          '</span><span class="tags"><span class="pill topic">' +
          esc(c.blocked ? "Bloqueado por spam" : statusLabel(c.status)) +
          "</span></span></button>",
      )
      .join("") +
    '</div></div><div class="c-detail">' +
    (c
      ? detail(c)
      : '<div class="empty">Nenhuma conversa ainda. Abra o simulador para começar.</div>') +
    "</div></section>";
  document.querySelectorAll(".c-item").forEach(
    (b) =>
      (b.onclick = () => {
        ui.conv = b.dataset.id;
        ui.mobileDetail = true;
        drawConvoBody();
      }),
  );
  if (!c) return;
  $(".back").onclick = () => {
    ui.mobileDetail = false;
    drawConvoBody();
  };
  $("#take")?.addEventListener("click", async () => {
    await api("/api/admin/conversations/" + c.id + "/claim", "POST");
    await refresh();
  });
  $("#release")?.addEventListener("click", async () => {
    await api("/api/admin/conversations/" + c.id + "/release", "POST");
    await refresh();
  });
  $("#unblock")?.addEventListener("click", async () => {
    await api("/api/admin/conversations/" + c.id + "/unblock", "POST");
    await refresh();
  });
  $("#humanForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#humanText");
    await api("/api/admin/conversations/" + c.id + "/messages", "POST", {
      content: input.value,
    });
    input.value = "";
    await refresh();
  });
  const thread = $(".thread");
  if (thread) thread.scrollTop = thread.scrollHeight;
}
function detail(c) {
  return (
    '<div class="d-head"><button class="btn btn-ghost btn-sm back">Voltar aos atendimentos</button><div class="who"><div><h2>' +
    esc(c.name) +
    '</h2><div class="ph">' +
    esc(statusLabel(c.status)) +
    '</div></div></div><div class="handover-actions">' +
    (c.status === "humano"
      ? '<button class="btn btn-ghost btn-sm" id="release">Sair e devolver à Lumi</button>'
      : '<button class="btn btn-primary btn-sm" id="take">Assumir atendimento</button>') +
    (c.blocked
      ? '<button class="btn btn-danger btn-sm" id="unblock">Desbloquear contato</button>'
      : "") +
    '</div></div>' + renderProfile(c.profile) + '<div class="thread">' +
    c.messages
      .map(
        (m) =>
          '<div class="msg ' +
          (m.sender === "cliente"
            ? "in"
            : m.sender === "sistema"
              ? "system"
              : "out") +
          '">' +
          (m.name ? "<strong>" + esc(m.name) + "</strong>" : "") +
          esc(m.content) +
          (m.image_id
            ? '<a href="/api/admin/images/' +
              m.image_id +
              '/file" target="_blank"><img src="/api/admin/images/' +
              m.image_id +
              '/file" alt="Imagem enviada pela Lumi"></a>'
            : "") +
          "<time>" +
          esc(
            m.sender === "lumi"
              ? "Lumi"
              : m.sender === "humano"
                ? m.name || "Operador"
                : "",
          ) +
          (m.delivery ? ' · ' + esc({pending:'Envio pendente',sending:'Enviando ao WhatsApp',sent:'Aceito pela Meta',delivered:'Entregue no WhatsApp',read:'Lido no WhatsApp',failed:'Falha no envio ao WhatsApp'}[m.delivery] || m.delivery) : '') + (m.delivery_error ? '<br>' + esc(m.delivery_error) : '') + "</time></div>",
      )
      .join("") +
    "</div>" +
    (c.status === "humano"
      ? '<form id="humanForm" class="reply-box"><input class="input" id="humanText" required placeholder="Sua resposta ao cliente"><button class="btn btn-primary">Enviar</button></form>'
      : "")
  );
}

window.addEventListener("DOMContentLoaded", () => { boot(); setInterval(() => refresh(), 1500); });
