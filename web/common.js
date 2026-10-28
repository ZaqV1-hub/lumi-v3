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
      el.append(document.createTextNode(m.content));
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
