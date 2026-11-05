const $ = (id) => document.getElementById(id);
async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Confira os campos e tente novamente.",
    );
  return data;
}
function appendMessageText(element, text) {
  let start = 0;
  for (const match of text.matchAll(/https?:\/\/[^\s<>"']+/g)) {
    let url = match[0].replace(/[.,!?;:]+$/, "");
    while (url.endsWith(")") && url.split(")").length > url.split("(").length) {
      url = url.slice(0, -1);
    }
    element.append(document.createTextNode(text.slice(start, match.index)));
    const link = document.createElement("a");
    link.href = url;
    link.textContent = url;
    const target = new URL(url);
    if (target.origin === location.origin && /^\/checkout\/[A-Za-z0-9_-]{40,80}$/.test(target.pathname)) {
      link.textContent = "Abrir página de pagamento";
    }
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    element.append(link, document.createTextNode(match[0].slice(url.length)));
    start = match.index + match[0].length;
  }
  element.append(document.createTextNode(text.slice(start)));
}
function drawMessages(items) {
  const nearBottom =
    $("messages").scrollHeight -
      $("messages").scrollTop -
      $("messages").clientHeight <
    80;
  $("messages").replaceChildren(
    ...items.map((m) => {
      const el = document.createElement("div");
      el.className = "bubble " + m.sender;
      if (m.name) {
        const name = document.createElement("strong");
        name.textContent = m.name;
        el.append(name);
      }
      appendMessageText(el, m.content);
      if(m.attachment_url){
        if(m.attachment_kind==='image'){
          const link=document.createElement('a');link.href=m.attachment_url;link.target='_blank';link.rel='noopener';
          const image=document.createElement('img');image.src=m.attachment_url;image.alt='Imagem enviada pelo cliente';image.style.cssText='display:block;max-width:100%;max-height:300px;border-radius:10px;margin-top:10px';link.append(image);el.append(link);
        }else if(m.attachment_kind==='audio'){
          const audio=document.createElement('audio');audio.controls=true;audio.preload='metadata';audio.src=m.attachment_url;audio.style.cssText='display:block;max-width:100%;margin-top:10px';el.append(audio);
        }
      }
      if (m.image_url) {
        const link = document.createElement('a');
        link.href = m.image_url;
        link.target = '_blank';
        const image = document.createElement('img');
        image.src = m.image_url;
        image.alt = 'Imagem enviada pela Lumi';
        image.style.cssText = 'display:block;max-width:100%;max-height:300px;border-radius:10px;margin-top:10px';
        link.append(image);
        el.append(link);
      }
      return el;
    }),
  );
  if (nearBottom) $("messages").scrollTop = $("messages").scrollHeight;
}
