const slug = location.pathname.split("/").pop(),
  key = "lumi-client-" + slug;
let token = sessionStorage.getItem(key),
  snapshot = "";
$("company").textContent = slug;
async function refresh() {
  if (!token) return;
  try {
    const data = await api("/api/client/" + token);
    $("start").hidden = true;
    $("chat").hidden = false;
    $("status").textContent = {
      lumi: "Lumi ativa",
      aguardando: "Aguardando atendimento humano",
      humano: "Atendimento humano",
    }[data.status];
    if (data.blocked) $('status').textContent = 'Atendimento bloqueado';
    $("human").hidden = data.status !== "lumi";
    const json = JSON.stringify(data.messages);
    if (json !== snapshot) {
      drawMessages(data.messages);
      snapshot = json;
    }
  } catch (e) {
    $("notice").textContent = e.message;
  }
}
$("start").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const data = await api("/api/public/" + slug + "/start", "POST", {
      name: $("name").value,
    });
    token = data.token;
    sessionStorage.setItem(key, token);
    $("company").textContent = data.tenant;
    await refresh();
  } catch (e) {
    $("notice").textContent = e.message;
  }
};
let pending = 0;
async function send(content) {
  pending += 1;
  $('text').value = '';
  $("notice").textContent = 'Mensagens em andamento: ' + pending;
  try {
    await api("/api/client/" + token + "/messages", "POST", { content });
    $("notice").textContent = "";
    await refresh();
  } catch (e) {
    $("notice").textContent = e.message;
  } finally {
    pending -= 1;
    if (pending) $('notice').textContent = 'Mensagens em andamento: ' + pending;
  }
}
$("sendForm").onsubmit = (e) => {
  e.preventDefault();
  if ($('text').value.trim()) send($("text").value);
};
$("human").onclick = () => send("Quero falar com um humano");
$("new").onclick = () => {
  sessionStorage.removeItem(key);
  location.reload();
};
refresh();
setInterval(refresh, 1200);
