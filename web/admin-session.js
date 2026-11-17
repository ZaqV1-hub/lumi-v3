const adminSession = (() => {
  let checking = false;
  let expiring = false;
  let lastSent = 0;
  let pendingActivity;
  let started = false;
  let cleanup;

  function expire() {
    if (expiring) return;
    expiring = true;
    clearTimeout(pendingActivity);
    cleanup?.();
    document.querySelector('#app').hidden = true;
    document.querySelector('#overlay').hidden = true;
    location.reload();
  }

  async function check(touch = false) {
    if (expiring || (checking && !touch)) return;
    if (!touch) checking = true;
    try {
      const response = await fetch('/api/session', {
        method: touch ? 'POST' : 'GET', cache: 'no-store', signal: AbortSignal.timeout(15000),
      });
      if (response.status === 401) expire();
    } catch {
      // A conexão pode voltar. O servidor ainda aplica o prazo da sessão.
    } finally {
      if (!touch) checking = false;
    }
  }

  function activity(event) {
    if (!event.isTrusted || document.hidden || expiring) return;
    if (pendingActivity) return;
    const send = () => {
      pendingActivity = undefined;
      lastSent = Date.now();
      void check(true);
    };
    const wait = 5000 - (Date.now() - lastSent);
    if (wait > 0) pendingActivity = setTimeout(send, wait);
    else send();
  }

  function start(onExpire) {
    if (started) return;
    started = true;
    cleanup = onExpire;
    for (const event of ['pointerdown', 'keydown', 'wheel', 'touchmove', 'input']) {
      document.addEventListener(event, activity, { capture: true, passive: true });
    }
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) void check();
    });
    window.addEventListener('focus', () => void check());
    window.addEventListener('pageshow', event => {
      if (event.persisted) void check();
    });
    setInterval(() => void check(), 15000);
  }

  return { start, expire };
})();

function adminDataStatus(element, label, retry) {
  element.innerHTML = retry
    ? '<div class="admin-data-status"><p role="alert"></p><button type="button" class="btn btn-ghost">Tentar novamente</button></div>'
    : '<div class="admin-data-status" role="status"><span class="admin-data-spinner" aria-hidden="true"></span><p></p></div>';
  element.querySelector('p').textContent = label;
  if (retry) element.querySelector('button').onclick = retry;
}