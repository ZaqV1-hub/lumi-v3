let pendingAttachment = null, mediaBusy = false, recording = null;
function clearAttachment() {
  if (pendingAttachment) URL.revokeObjectURL(pendingAttachment.url);
  pendingAttachment = null; $('tray').hidden = true; $('trayImg').removeAttribute('src'); $('file').value = ''; syncComposer();
}
function stageAttachment(file) {
  if (!token || mediaBusy || recording) return;
  const image = ['image/png','image/jpeg','image/webp'].includes(file.type);
  if (!image && !file.type.startsWith('audio/')) { setNotice('Envie uma imagem PNG, JPG ou WebP, ou um áudio.'); return; }
  if (!file.size || file.size > (image ? 5 : 12) * 1024 * 1024) { setNotice('Arquivo vazio ou grande demais. Imagem: até 5 MB; áudio: até 12 MB.'); return; }
  clearAttachment(); pendingAttachment = {file, url:URL.createObjectURL(file)};
  $('trayImg').hidden = !image; if (image) $('trayImg').src = pendingAttachment.url;
  $('trayName').textContent = file.name || (image ? 'Imagem' : 'Áudio');
  $('traySize').textContent = (file.size / 1024 < 1024 ? Math.round(file.size / 1024) + ' KB' : (file.size / 1048576).toFixed(1) + ' MB');
  $('tray').hidden = false; setNotice(); syncComposer(); text.focus();
}
async function sendAttachment(file = pendingAttachment?.file, caption = text.value.trim()) {
  if (mediaBusy || !file || !token) return;
  if (caption.length > 2000) { setNotice('Use uma legenda de até 2.000 caracteres.'); return; }
  const current = token; mediaBusy = true; pending++; scrollAfterSend = true; setNotice(); syncComposer();
  try {
    const response = await fetch('/api/client/' + current + '/attachments', {method:'POST',
      headers:{'Content-Type':file.type || 'application/octet-stream', 'X-Lumi-Caption':encodeURIComponent(caption)}, body:file});
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível enviar o arquivo.');
    if (current !== token) return;
    clearAttachment(); text.value = ''; resizeText(); if (data.blocked) setNotice('Atendimento bloqueado.'); await refresh();
  } catch (error) {
    if (current === token) { if (!pendingAttachment) stageRecordingForRetry(file); setNotice(error.message); }
  } finally { if (current === token) { mediaBusy = false; pending--; syncComposer(); } }
}
function stageRecordingForRetry(file) {
  pendingAttachment = {file, url:URL.createObjectURL(file)}; $('trayImg').hidden = true;
  $('trayName').textContent = 'Áudio gravado'; $('traySize').textContent = 'Pronto para tentar novamente'; $('tray').hidden = false;
}
$('attach').onclick = () => $('file').click();
$('file').onchange = () => { const file = $('file').files[0]; if (file) stageAttachment(file); $('file').value = ''; };
$('trayX').onclick = () => { if (!mediaBusy) clearAttachment(); };
document.addEventListener('paste', event => {
  if (!token || mediaBusy || recording || !$('overlay').hidden) return;
  const item = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/'));
  if (item) { event.preventDefault(); const file = item.getAsFile(); if (file) stageAttachment(file); }
});
for (const name of ['dragenter', 'dragover']) thread.addEventListener(name, event => {
  if ([...(event.dataTransfer?.types || [])].includes('Files')) { event.preventDefault(); thread.classList.add('drop'); }
});
thread.addEventListener('dragleave', () => thread.classList.remove('drop'));
thread.addEventListener('drop', event => { event.preventDefault(); thread.classList.remove('drop'); if (event.dataTransfer.files[0]) stageAttachment(event.dataTransfer.files[0]); });
function recordingUI(active) {
  $('composer').hidden = active; $('rec').hidden = !active; $('rlabel').hidden = !active; $('hint').hidden = active;
  if (!active) { syncComposer(); text.focus(); }
}
function stopRecordingResources(state) {
  clearInterval(state.timer); state.stream?.getTracks().forEach(track => track.stop()); state.context?.close().catch(() => {});
}
async function startRecording() {
  if (!token || mediaBusy || recording) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setNotice('Microfone indisponível. Você pode anexar um arquivo de áudio.'); return; }
  const state = {parts:[], started:0}; recording = state; recordingUI(true);
  $('recGo').disabled = true; $('recT').textContent = '0:00'; $('live').replaceChildren();
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({audio:true});
    if (recording !== state) { stopRecordingResources(state); return; }
    state.recorder = new MediaRecorder(state.stream);
    state.recorder.ondataavailable = event => { if (event.data.size) state.parts.push(event.data); };
    state.recorder.onstop = () => {
      stopRecordingResources(state); if (!state.cancelled) sendAttachment(new Blob(state.parts, {type:state.recorder.mimeType}), '');
    };
    state.recorder.start(); state.started = Date.now(); $('recGo').disabled = false; setNotice();
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      state.context = new AudioContext(); state.analyser = state.context.createAnalyser(); state.analyser.fftSize = 256;
      state.context.createMediaStreamSource(state.stream).connect(state.analyser); state.samples = new Uint8Array(state.analyser.fftSize);
    }
    state.timer = setInterval(() => {
      const seconds = Math.floor((Date.now() - state.started) / 1000);
      $('recT').textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
      if (state.analyser) {
        state.analyser.getByteTimeDomainData(state.samples);
        const level = Math.max(3, Math.min(30, Math.max(...state.samples.map(value => Math.abs(value - 128))) / 2));
        const bar = document.createElement('i'); bar.style.height = level + 'px'; $('live').append(bar);
        while ($('live').children.length > 55) $('live').firstChild.remove();
      }
      if (seconds >= 120) finishAudio();
    }, 100);
  } catch {
    state.cancelled = true; if (state.recorder?.state === 'recording') state.recorder.stop(); stopRecordingResources(state);
    if (recording === state) { recording = null; recordingUI(false); setNotice('Não foi possível acessar o microfone. Você pode anexar um áudio.'); }
  }
}
function finishAudio() {
  const state = recording; if (!state?.started) return;
  state.cancelled = Date.now() - state.started < 1000; recording = null;
  clearInterval(state.timer); state.recorder.stop(); recordingUI(false);
  if (state.cancelled) setNotice('Grave pelo menos um segundo antes de enviar.');
}
function cancelAudio() {
  const state = recording; if (!state) return;
  state.cancelled = true; recording = null; if (state.recorder?.state === 'recording') state.recorder.stop();
  stopRecordingResources(state); recordingUI(false);
}
$('recGo').onclick = finishAudio; $('recX').onclick = cancelAudio;
window.addEventListener('pagehide', () => { cancelAudio(); if (pendingAttachment) URL.revokeObjectURL(pendingAttachment.url); });
