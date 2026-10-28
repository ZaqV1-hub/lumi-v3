/* Imagens da Lumi */
function drawImgs() {
  const q = ui.imq.toLowerCase();
  const list = imgs.filter(
    (i) =>
      !q || [i.name, i.desc, i.when].some((t) => t.toLowerCase().includes(q)),
  );
  $("#cfgBody").innerHTML =
    `<div style="display:flex;flex-direction:column;gap:14px">
    <p class="intro">Envie imagens para a Lumi usar nas conversas. Dê um nome, descreva o que a imagem mostra e diga em que situação ela deve ser usada. A Lumi decide quando enviar com base nessa instrução.</p>
    <div class="kb-tools"><div class="search">${searchIco}<input class="input" id="imq" placeholder="Buscar imagens" value="${esc(ui.imq)}"></div><button class="btn btn-primary" id="imAdd">Adicionar imagem</button></div>
    <span class="kb-count num">${list.length} de ${imgs.length} imagens</span>
    <div class="img-grid">${
      list.length
        ? list
            .map(
              (i) => `<article class="card img-card">
      <button class="thumb" type="button" data-view="${i.id}" aria-label="Ampliar ${esc(i.name)}"><img src="${i.src}" alt="${esc(i.name)}"></button>
      <div class="img-body"><h3>${esc(i.name)}</h3><p class="desc">${esc(i.desc)}</p>
        <div class="when"><span>Quando usar</span>${esc(i.when)}</div>
        <div class="foot">${ui.confirmImg === i.id ? `<span class="confirm">Excluir esta imagem?</span><div class="acts"><button class="btn btn-ghost btn-sm" data-cancel>Não</button><button class="btn btn-danger btn-sm" data-yes="${i.id}">Excluir</button></div>` : `<small>Atualizado em<br><span class="num">${i.d}</span></small><div class="acts"><button class="btn btn-ghost btn-sm" data-edit="${i.id}">Editar</button><button class="btn btn-danger btn-sm" data-del="${i.id}">Excluir</button></div>`}</div>
      </div></article>`,
            )
            .join("")
        : `<div class="card empty" style="grid-column:1/-1">${imgs.length ? `Nenhuma imagem encontrada para "${esc(ui.imq)}".` : "Nenhuma imagem ainda. Clique em Adicionar imagem para enviar a primeira."}</div>`
    }</div></div>`;
  $("#imq").oninput = (e) => {
    ui.imq = e.target.value;
    const p = e.target.selectionStart;
    drawImgs();
    const n = $("#imq");
    n.focus();
    n.setSelectionRange(p, p);
  };
  $("#imAdd").onclick = () => imgModal();
  const b = $("#cfgBody");
  b.querySelectorAll("[data-view]").forEach(
    (x) =>
      (x.onclick = () => viewImg(imgs.find((i) => i.id === x.dataset.view))),
  );
  b.querySelectorAll("[data-edit]").forEach(
    (x) =>
      (x.onclick = () => imgModal(imgs.find((i) => i.id === x.dataset.edit))),
  );
  b.querySelectorAll("[data-del]").forEach(
    (x) =>
      (x.onclick = () => {
        ui.confirmImg = x.dataset.del;
        drawImgs();
      }),
  );
  b.querySelectorAll("[data-cancel]").forEach(
    (x) =>
      (x.onclick = () => {
        ui.confirmImg = null;
        drawImgs();
      }),
  );
  b.querySelectorAll("[data-yes]").forEach(
    (x) =>
      (x.onclick = async () => {
        await api("/api/admin/images/" + x.dataset.yes, "DELETE");
        await loadImages();
        ui.confirmImg = null;
        drawImgs();
        toast("Imagem excluída");
      }),
  );
}
function viewImg(i) {
  const close =
    openModal(`<div class="modal lb" role="dialog" aria-modal="true" aria-label="${esc(i.name)}">
    <img src="${i.src}" alt="${esc(i.name)}"><h2>${esc(i.name)}</h2><p>${esc(i.desc)}</p>
    <div class="when"><span>Quando usar</span>${esc(i.when)}</div>
    <div class="acts"><button class="btn btn-ghost" id="lbClose" type="button">Fechar</button></div></div>`);
  $("#lbClose").onclick = close;
  $("#lbClose").focus();
}
function imgModal(item) {
  let src = item ? item.src : "";
  const close =
    openModal(`<form class="modal" id="imForm" role="dialog" aria-modal="true" aria-labelledby="imTitle">
    <h2 id="imTitle">${item ? "Editar imagem" : "Adicionar imagem"}</h2>
    <label class="drop ${src ? "has" : ""}" id="imDrop" for="imF"><input class="sr" type="file" id="imF" accept="image/png,image/jpeg,image/webp"><span class="d-empty"><b>Arraste uma imagem ou clique para escolher</b><span>PNG, JPG ou WebP, até 5 MB</span></span>${src ? `<img src="${src}" alt=""><span class="swap">Trocar imagem</span>` : ""}</label>
    <div class="field"><label for="imN">Nome</label><input class="input" id="imN" maxlength="60" placeholder="Ex.: Mapa do parque"></div>
    <div class="field"><label for="imD">Descrição</label><textarea class="input" id="imD" maxlength="240" style="min-height:84px" placeholder="O que a imagem mostra."></textarea></div>
    <div class="field"><label for="imW">Quando usar</label><textarea class="input" id="imW" maxlength="200" style="min-height:84px" placeholder="Ex.: Envie quando o cliente perguntar como chegar ou onde fica uma atração."></textarea><span class="counter num" id="imC">0/200</span></div>
    <p class="err" id="imErr" hidden></p>
    <div class="acts"><button type="button" class="btn btn-ghost" id="imCancel">Cancelar</button><button class="btn btn-primary" type="submit">${item ? "Salvar" : "Adicionar"}</button></div></form>`);
  if (item) {
    $("#imN").value = item.name;
    $("#imD").value = item.desc;
    $("#imW").value = item.when;
  }
  const cnt = () => {
    $("#imC").textContent = $("#imW").value.length + "/200";
  };
  cnt();
  $("#imW").oninput = cnt;
  const drop = $("#imDrop"),
    f = $("#imF"),
    err = $("#imErr");
  const fail = (m) => {
    err.textContent = m;
    err.hidden = false;
  };
  function setFile(file) {
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      fail("Use uma imagem PNG, JPG ou WebP.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      fail("A imagem passa de 5 MB. Escolha uma menor.");
      return;
    }
    const r = new FileReader();
    r.onload = () => {
      src = r.result;
      drop.classList.add("has");
      let im = drop.querySelector("img");
      if (!im) {
        im = document.createElement("img");
        im.alt = "";
        drop.appendChild(im);
        const s = document.createElement("span");
        s.className = "swap";
        s.textContent = "Trocar imagem";
        drop.appendChild(s);
      }
      im.src = src;
      err.hidden = true;
    };
    r.onerror = () => fail("Não foi possível ler essa imagem. Tente outra.");
    r.readAsDataURL(file);
  }
  f.onchange = () => setFile(f.files[0]);
  ["dragenter", "dragover"].forEach((t) =>
    drop.addEventListener(t, (e) => {
      e.preventDefault();
      drop.classList.add("over");
    }),
  );
  ["dragleave", "drop"].forEach((t) =>
    drop.addEventListener(t, (e) => {
      e.preventDefault();
      drop.classList.remove("over");
    }),
  );
  drop.addEventListener("drop", (e) =>
    setFile(e.dataTransfer && e.dataTransfer.files[0]),
  );
  $("#imCancel").onclick = close;
  $("#imForm").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#imN").value.trim(),
      desc = $("#imD").value.trim(),
      when = $("#imW").value.trim();
    if (!src) {
      fail("Escolha uma imagem para enviar.");
      return;
    }
    if (!name || !desc || !when) {
      fail("Preencha o nome, a descrição e quando usar.");
      return;
    }
    await api(
      "/api/admin/images" + (item ? "/" + item.id : ""),
      item ? "PUT" : "POST",
      {
        name,
        description: desc,
        when_to_use: when,
        src: src.startsWith("data:") ? src : null,
      },
    );
    await loadImages();
    close();
    drawImgs();
    toast(
      item ? "Imagem atualizada" : "Imagem adicionada. A Lumi já pode usá-la.",
    );
  };
}
