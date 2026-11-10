/* Human calls live outside #content, which the conversation refresh replaces. */
const calling = (() => {
  let view = null, session = null, bar, audio;
  const permissionAttempts = new Map();
  const key = () => Array.from(crypto.getRandomValues(new Uint8Array(24)), byte => byte.toString(16).padStart(2, '0')).join('');
  const tab = key();
  const tenant = () => new URLSearchParams(location.search).get('tenant') || '';
  const rejected = error => error.status >= 400 && error.status < 500 && error.status !== 408;
  const endpoint = (ctx, suffix = '') => ctx.path + suffix + (ctx.tenant ? '?tenant=' + encodeURIComponent(ctx.tenant) : '');
  const permissionLabels = {unknown:'Permissão não verificada', absent:'Permissão necessária', pending:'Aguardando permissão', granted:'Permissão concedida', denied:'Permissão recusada', expired:'Permissão expirada', revoked:'Permissão revogada'};
  const callLabels = {preparing:'Preparando microfone', reserved:'Preparando chamada', initiating:'Chamando', ringing:'Chamando', accepted:'Conectando áudio', terminating:'Encerrando chamada', uncertain:'Resultado incerto · reconciliando', ended:'Chamada encerrada', rejected:'Chamada recusada', failed:'Falha na chamada', canceled:'Chamada cancelada'};

  async function request(ctx, suffix = '', body, keepalive = false) {
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 20000);
    try {
      const response = await fetch(endpoint(ctx, suffix), {method:body === undefined ? 'GET' : 'POST', credentials:'same-origin', cache:'no-store', keepalive,
        headers:{'Content-Type':'application/json', 'X-Calling-Tab':tab}, body:body === undefined ? undefined : JSON.stringify(body), signal:abort.signal});
      if (!response.ok) throw Object.assign(Error('Não foi possível concluir. Atualize o estado e tente novamente.'), {status:response.status});
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  function controls() {
    const el = document.querySelector('#calling-controls');
    if (!view || !el || el.dataset.conversation !== view.id) return;
    const data = view.data, state = data?.permission?.state || 'unknown';
    const active = data?.active_call?.active;
    let description = data?.block_reason || 'O cliente autoriza a ligação pelo WhatsApp.';
    if (state === 'granted' && !data.block_reason) {
      const expiry = data.permission.expires_at;
      description = expiry ? 'Válida até ' + new Date(expiry).toLocaleString('pt-BR') : 'Válida até o cliente revogar.';
    }
    if (active) description = session?.id === data.active_call.id ? 'Chamada em andamento na barra abaixo.' : 'Chamada em outra aba ou sessão. Aguarde a reconciliação antes de ligar.';
    el.className = 'calling-controls calling-' + state;
    const html = '<div class="calling-copy"><b>' + esc(permissionLabels[state] || permissionLabels.unknown) + '</b><span>' + esc(description) + '</span></div>' +
      '<div class="calling-actions"><button class="btn btn-ghost btn-sm" data-calling="permission"' + (!data?.can_request_permission || view.busy || view.permissionKey ? ' disabled' : '') + '>Pedir permissão</button>' +
      '<button class="btn btn-primary btn-sm" data-calling="start"' + (!data?.can_call || view.busy || session ? ' disabled' : '') + '>Ligar pelo WhatsApp</button></div>' +
      '<p class="calling-error" role="alert" tabindex="-1"' + (view.error ? '' : ' hidden') + '>' + esc(view.error || '') + '</p>' + history(data?.history || []);
    if (el.callingMarkup !== html) {
      const historyOpen = el.querySelector('details')?.open;
      const focusedError = document.activeElement === el.querySelector('.calling-error');
      const focused = el.contains(document.activeElement) ? document.activeElement.dataset.calling : null;
      el.innerHTML = html; el.callingMarkup = html;
      if (historyOpen && el.querySelector('details')) el.querySelector('details').open = true;
      if (focusedError) el.querySelector('.calling-error')?.focus();
      if (focused) el.querySelector('[data-calling="'+focused+'"]')?.focus();
    }
    el.querySelector('[data-calling="permission"]').onclick = () => askPermission(view);
    el.querySelector('[data-calling="start"]').onclick = () => start(view);
    const release = document.querySelector('#release');
    if (release) {release.disabled = Boolean(active || (session && session.ctx.id === view.id)); release.title = release.disabled ? 'Encerre a chamada antes de devolver à Lumi.' : '';}
  }
  function history(items) {
    if (!items.length) return '';
    return '<details class="calling-history"><summary>Chamadas recentes</summary><ol>' + items.map(item => '<li><b>' + esc(item.state === 'accepted' ? 'Chamada aceita' : callLabels[item.state] || 'Estado indisponível') + '</b><span>' + esc(item.operator_name || 'Operador') + ' · ' + esc(new Date(item.created_at).toLocaleString('pt-BR')) + (item.error_code ? ' · Falha registrada no atendimento' : '') + '</span></li>').join('') + '</ol></details>';
  }
  function error(ctx, message, focus = true) {
    ctx.error = message;
    if (view === ctx) {controls(); if (focus) document.querySelector('.calling-error')?.focus();}
  }
  async function refresh(ctx) {
    if (ctx.loading) return;
    clearTimeout(ctx.timer);
    ctx.loading = true;
    try {
      const data = await request(ctx);
      if (view !== ctx || tenant() !== ctx.tenant) return;
      ctx.data = data;
      if (ctx.lookupFailed) {ctx.error = ''; ctx.lookupFailed = false;}
      if (data.permission.state !== 'absent' && data.permission.state !== 'unknown') {ctx.permissionKey = null; permissionAttempts.delete(endpoint(ctx));}
      controls();
    } catch {
      if (view === ctx) {ctx.data = null; ctx.lookupFailed = true; error(ctx, 'Não foi possível consultar as chamadas. Aguardando atualização.', false);}
    } finally {
      ctx.loading = false;
      if (view === ctx) ctx.timer = setTimeout(() => refresh(ctx), 5000);
    }
  }
  async function askPermission(ctx) {
    if (ctx.busy || ctx.permissionKey || !ctx.data?.can_request_permission) return;
    ctx.busy = true; ctx.error = ''; ctx.permissionKey = key(); permissionAttempts.set(endpoint(ctx), ctx.permissionKey); controls();
    try {
      const result = await request(ctx, '/permission', {idempotency_key:ctx.permissionKey});
      if (result.state === 'failed') {ctx.permissionKey = null; permissionAttempts.delete(endpoint(ctx)); error(ctx, 'O pedido de permissão falhou. Consulte o estado antes de tentar novamente.');}
      else if (result.state === 'uncertain') error(ctx, 'Resultado do pedido incerto. Aguarde a confirmação; não reenvie.');
      else if (ctx.data) ctx.data.permission.state = 'pending';
    } catch (e) {
      if (rejected(e)) {ctx.permissionKey = null; permissionAttempts.delete(endpoint(ctx));}
      error(ctx, rejected(e) ? e.message : 'Resultado do pedido incerto. Aguarde a confirmação; não reenvie.');
    } finally {ctx.busy = false; if (view === ctx) {controls(); refresh(ctx);}}
  }
  function stableRegion() {
    if (bar) return;
    bar = document.createElement('section'); bar.id = 'calling-bar'; bar.hidden = true; bar.setAttribute('aria-label', 'Chamada WhatsApp');
    bar.innerHTML = '<div class="calling-avatar" aria-hidden="true">☎</div><div class="calling-bar-copy"><span id="calling-status" role="status"></span><b id="calling-name"></b><span id="calling-media"></span></div><time id="calling-duration"></time><div class="calling-actions"><button class="btn btn-ghost" id="calling-play" hidden>Ouvir áudio</button><button class="btn btn-ghost" id="calling-mute" aria-pressed="false">Silenciar microfone</button><button class="btn btn-danger" id="calling-end">Encerrar chamada</button><button class="btn btn-ghost" id="calling-dismiss" hidden>Fechar</button></div>';
    audio = document.createElement('audio'); audio.autoplay = true; audio.setAttribute('playsinline', '');
    document.body.append(bar, audio);
    bar.querySelector('#calling-mute').onclick = () => {
      if (!session?.stream) return;
      session.muted = !session.muted;
      session.stream.getAudioTracks().forEach(track => {track.enabled = !session.muted;}); paint();
    };
    bar.querySelector('#calling-end').onclick = () => stop(session);
    bar.querySelector('#calling-dismiss').onclick = () => {bar.hidden = true; document.body.classList.remove('calling-visible');};
    bar.querySelector('#calling-play').onclick = () => audio.play().then(() => {bar.querySelector('#calling-play').hidden = true;}).catch(() => {});
  }
  function paint(s = session) {
    if (!s || session !== s) return;
    stableRegion(); bar.dataset.tenant = s.ctx.tenant; bar.hidden = false; document.body.classList.add('calling-visible');
    const connected = s.state === 'accepted' && s.peer?.connectionState === 'connected';
    if (connected && !s.connectedAt) s.connectedAt = Date.now();
    const status = bar.querySelector('#calling-status'), label = connected ? 'Em ligação' : callLabels[s.state] || 'Aguardando estado da chamada';
    if (status.textContent !== label) status.textContent = label;
    bar.querySelector('#calling-name').textContent = s.ctx.name;
    bar.querySelector('#calling-media').textContent = s.error || (s.muted ? 'Microfone silenciado' : s.peer?.connectionState === 'disconnected' ? 'Áudio desconectado' : 'Ligação de áudio pelo WhatsApp');
    const seconds = s.connectedAt ? Math.floor((Date.now() - s.connectedAt) / 1000) : 0;
    bar.querySelector('#calling-duration').textContent = s.connectedAt ? Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0') : '';
    bar.querySelector('#calling-mute').disabled = !s.stream;
    bar.querySelector('#calling-mute').setAttribute('aria-pressed', String(Boolean(s.muted)));
    bar.querySelector('#calling-mute').textContent = s.muted ? 'Ativar microfone' : 'Silenciar microfone';
    bar.querySelector('#calling-end').disabled = Boolean(s.stopping);
    bar.querySelector('#calling-end').textContent = s.connectedAt ? 'Encerrar chamada' : 'Cancelar chamada';
    controls();
  }
  function mediaOff(s) {
    s.cancelIce?.(); s.cancelIce = null;
    s.stream?.getTracks().forEach(track => track.stop()); s.stream = null;
    if (s.peer) {s.peer.onconnectionstatechange = null; s.peer.ontrack = null; s.peer.close(); s.peer = null;}
    if (audio) {audio.pause(); audio.srcObject = null;}
  }
  function finish(s) {
    if (session !== s) return;
    mediaOff(s); clearTimeout(s.pollTimer); clearTimeout(s.heartbeatTimer); clearInterval(s.clock);
    paint(s); session = null;
    bar.querySelector('#calling-mute').hidden = true; bar.querySelector('#calling-end').hidden = true; bar.querySelector('#calling-dismiss').hidden = false;
    if (view) refresh(view);
    controls();
  }
  function iceComplete(s) {
    return new Promise((resolve, reject) => {
      const peer = s.peer;
      const done = (error) => {clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', changed); s.cancelIce = null; error ? reject(error) : resolve();};
      const changed = () => {if (peer.iceGatheringState === 'complete') done();};
      const timer = setTimeout(() => done(Error('Não foi possível preparar a conexão de áudio. Confira sua rede.')), 12000);
      s.cancelIce = () => done(Error('Preparo cancelado.'));
      peer.addEventListener('icegatheringstatechange', changed); changed();
    });
  }
  async function start(ctx) {
    if (session || !ctx.data?.can_call || ctx.tenant !== tenant()) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {error(ctx, 'Para ligar, use um navegador compatível em HTTPS ou localhost.'); return;}
    const s = session = {ctx:{id:ctx.id, name:ctx.name, path:ctx.path, tenant:ctx.tenant}, state:'preparing', key:key(), terminateKey:key()};
    ctx.error = ''; stableRegion();
    bar.querySelector('#calling-mute').hidden = false; bar.querySelector('#calling-end').hidden = false; bar.querySelector('#calling-dismiss').hidden = true; bar.querySelector('#calling-play').hidden = true;
    s.clock = setInterval(() => {if (tenant() !== s.ctx.tenant) dispose(); else paint(s);}, 1000); paint(s);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio:true, video:false});
      if (tenant() !== s.ctx.tenant) dispose();
      if (session !== s || s.stopping) {stream.getTracks().forEach(track => track.stop()); return;}
      s.stream = stream; s.peer = new RTCPeerConnection({iceServers:[]});
      s.peer.addTrack(stream.getAudioTracks()[0], stream);
      const opus = RTCRtpReceiver.getCapabilities('audio').codecs.filter(codec => codec.mimeType.toLowerCase() === 'audio/opus' && codec.clockRate === 48000);
      if (!opus.length) throw Error('Este navegador não oferece áudio Opus.');
      s.peer.getTransceivers()[0].setCodecPreferences(opus);
      s.peer.ontrack = event => {
        if (session !== s) return;
        audio.srcObject = event.streams[0] || new MediaStream([event.track]);
        audio.play().catch(() => {if (session === s) bar.querySelector('#calling-play').hidden = false;});
      };
      s.peer.onconnectionstatechange = () => {
        if (session !== s) return;
        if (s.peer.connectionState === 'failed') {s.error = 'A conexão de áudio falhou. Encerrando a chamada.'; stop(s);}
        else paint(s);
      };
      const offer = await s.peer.createOffer();
      // Only audio packetization is constrained; ICE and DTLS remain browser-negotiated.
      offer.sdp = offer.sdp.replace(/^a=(?:maxptime|ptime):.*\r?\n/gm, '') + 'a=ptime:20\r\na=maxptime:20\r\n';
      await s.peer.setLocalDescription(offer); await iceComplete(s);
      if (tenant() !== s.ctx.tenant) dispose();
      if (session !== s || s.stopping) return;
      s.state = 'initiating'; s.posted = true; paint(s);
      const result = await request(s.ctx, '/calls', {idempotency_key:s.key, sdp_offer:s.peer.localDescription.sdp});
      if (session !== s) {
        if (result.active) request(s.ctx, '/calls/'+encodeURIComponent(result.id)+'/terminate', {idempotency_key:s.terminateKey}, true).catch(() => {});
        return;
      }
      s.id = result.id;
      await apply(s, result);
      if (session === s) {poll(s); heartbeat(s);}
    } catch (e) {
      if (session !== s) return;
      if (!s.posted || rejected(e)) {
        s.state = 'failed'; s.error = e.name === 'NotAllowedError' ? 'Microfone bloqueado. Permita o acesso no navegador para ligar.' : e.status ? e.message : 'Não foi possível preparar o áudio. Confira microfone e conexão.';
        error(ctx, s.error); finish(s);
      } else {
        mediaOff(s); s.state = 'uncertain'; s.stopping = true;
        s.error = 'Não foi possível confirmar o início. Aguardando reconciliação; não ligue novamente.'; paint(s); poll(s);
      }
    }
  }
  async function apply(s, result) {
    if (session !== s) return;
    s.state = result.state;
    if (!result.active) {s.error = ''; finish(s); return;}
    if (s.stopping) {await stop(s); return;}
    if (result.answer_sdp && s.peer && s.answer !== result.answer_sdp) {
      await s.peer.setRemoteDescription({type:'answer', sdp:result.answer_sdp});
      s.answer = result.answer_sdp;
    }
    paint(s);
  }
  async function poll(s) {
    if (session !== s) return;
    try {
      if (!s.id) {
        const data = await request(s.ctx, '/calls/by-key/'+encodeURIComponent(s.key));
        if (data.call) {s.id = data.call.id; await apply(s, data.call);}
      } else await apply(s, await request(s.ctx, '/calls/'+encodeURIComponent(s.id)));
    } catch (e) {
      if (session !== s) return;
      s.error = 'Não foi possível atualizar a chamada. Aguardando reconciliação.';
      if (e.status === 401 || e.status === 403 || e.status === 404) {s.state = 'uncertain'; finish(s);}
      else if (s.peer && e.name !== 'TypeError' && !e.status) {s.error = 'Falha na negociação de áudio. Encerrando a chamada.'; await stop(s);}
      else paint(s);
    } finally {if (session === s) s.pollTimer = setTimeout(() => poll(s), s.id ? 1000 : 5000);}
  }
  async function heartbeat(s) {
    if (session !== s || !s.id || s.stopping) return;
    try {await request(s.ctx, '/calls/'+encodeURIComponent(s.id)+'/heartbeat', {browser_state:s.peer?.connectionState || 'closed'});}
    catch {if (session === s) {s.error = 'Presença não confirmada. O servidor pode encerrar a chamada.'; paint(s);}}
    finally {if (session === s && !s.stopping) s.heartbeatTimer = setTimeout(() => heartbeat(s), 10000);}
  }
  async function stop(s) {
    if (!s || session !== s || s.terminating) return;
    s.stopping = true; mediaOff(s); clearTimeout(s.heartbeatTimer);
    if (!s.posted) {s.state = 'canceled'; finish(s); return;}
    s.state = 'terminating'; paint(s);
    if (!s.id) return;
    s.terminating = true;
    try {await request(s.ctx, '/calls/'+encodeURIComponent(s.id)+'/terminate', {idempotency_key:s.terminateKey});}
    catch {s.error = 'Encerramento ainda não confirmado. Aguardando reconciliação.';}
    finally {paint(s);}
  }
  function mount(conversation) {
    if ((session && session.ctx.tenant !== tenant()) || (bar && bar.dataset.tenant !== tenant())) dispose();
    if (!conversation || conversation.channel !== 'whatsapp') {if (view) clearTimeout(view.timer); view = null; return;}
    if (view?.id !== conversation.id || view?.tenant !== tenant()) {
      if (view) clearTimeout(view.timer);
      view = {id:conversation.id, name:conversation.name, tenant:tenant(), path:'/api/admin/conversations/'+encodeURIComponent(conversation.id)+'/calling'};
      view.permissionKey = permissionAttempts.get(endpoint(view));
      refresh(view);
    }
    controls();
  }
  function dispose() {
    if (view) clearTimeout(view.timer); view = null;
    const s = session;
    if (s) {
      if (s.id) request(s.ctx, '/calls/'+encodeURIComponent(s.id)+'/terminate', {idempotency_key:s.terminateKey}, true).catch(() => {});
      mediaOff(s); clearTimeout(s.pollTimer); clearTimeout(s.heartbeatTimer); clearInterval(s.clock); session = null;
    }
    if (bar) {bar.hidden = true; bar.dataset.tenant = tenant();}
    document.body.classList.remove('calling-visible');
  }
  window.addEventListener('pagehide', dispose);
  return {mount, dispose};
})();
function renderCallingControls(conversation) {
  return conversation.channel === 'whatsapp' ? '<section id="calling-controls" class="calling-controls" aria-label="Ligação pelo WhatsApp" data-conversation="'+esc(conversation.id)+'">Consultando permissão de chamada…</section>' : '';
}
function mountCallingControls(conversation) {calling.mount(conversation);}
function disposeCalling() {calling.dispose();}
