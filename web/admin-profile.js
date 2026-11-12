function paintAccountName() {
  $('#userBtn .name').textContent = me.name;
  $('#userBtn .av').textContent = me.name[0];
  $('.um-id b').textContent = me.name + ' · ' + me.tenant;
  $('.um-id span').textContent = '';
}

$('#editProfile').onclick = () => {
  closeUserMenu();
  const close = openModal(`<form class="modal profile-editor" role="dialog" aria-modal="true" aria-labelledby="editProfileTitle">
    <h2 id="editProfileTitle">Alterar dados</h2>
    <label>Nome de atendimento<input class="input" name="name" autocomplete="name" maxlength="120" required value="${esc(me.name)}"></label>
    <details><summary>Alterar senha</summary>
      <label>Senha atual<input class="input" name="current_password" type="password" autocomplete="current-password"></label>
      <label>Nova senha<input class="input" name="password" type="password" autocomplete="new-password" minlength="8"></label>
      <label>Confirme a nova senha<input class="input" name="confirm_password" type="password" autocomplete="new-password" minlength="8"></label>
    </details>
    <p role="alert" hidden></p>
    <div class="profile-actions"><button type="button" class="btn btn-ghost">Cancelar</button><button class="btn btn-primary" type="submit">Salvar</button></div>
  </form>`);
  const form = $('.profile-editor'), error = form.querySelector('[role="alert"]');
  form.elements.name.focus();
  form.querySelector('[type="button"]').onclick = () => { close(); $('#userBtn').focus(); };
  form.onsubmit = async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    if (!form.querySelector('details').open) {
      delete data.current_password; delete data.password; delete data.confirm_password;
    } else {
      for (const key of ['current_password','password','confirm_password']) if (!data[key]) delete data[key];
    }
    if ((data.password || data.confirm_password) && data.password !== data.confirm_password) {
      error.hidden = false; error.textContent = 'As novas senhas precisam ser iguais.'; return;
    }
    const save = event.submitter;
    save.disabled = true;
    try {
      const result = await api('/api/me/profile', 'PUT', data);
      me.name = result.name;
      paintAccountName();
      close();
      $('#userBtn').focus();
      toast('Dados atualizados.');
    } catch (failure) {
      error.textContent = failure.message; error.hidden = false;
    } finally { save.disabled = false; }
  };
};
