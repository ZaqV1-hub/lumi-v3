let conversationList;
let conversationThread;
let searchTimer;

function conversationFilter() {
  return { [statusLabel('lumi')]: 'lumi', 'Aguardando atendimento': 'aguardando', 'Atendimento humano': 'humano' }[ui.tp] || '';
}

function openConversationList(openFirst = false) {
  clearTimeout(searchTimer);
  conversationList = { items: null, cursor: null, pages: 0, busy: false, error: false };
  renderConvos();
  void loadConversationPage({ openFirst });
  if (ui.conv) void loadConversationThread();
}

function setConversationFilter(value, openFirst = false) {
  ui.tp = value;
  ui.q = '';
  ui.conv = '';
  ui.mobileDetail = false;
  conversationThread = null;
  openConversationList(openFirst);
  document.querySelector('.conversation-tabs [aria-pressed="true"]')?.focus({ preventScroll: true });
}

function searchConversations(value) {
  ui.q = value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    ui.conv = '';
    ui.mobileDetail = false;
    conversationThread = null;
    openConversationList();
  }, 250);
}

async function loadConversationPage({ more = false, quiet = false, openFirst = false } = {}) {
  const list = conversationList;
  if (!list || (more && !list.cursor)) return;
  if (list.busy) {
    if (more) list.moreRequested = true;
    return;
  }
  list.busy = true;
  list.error = false;
  if (!quiet) renderConvos();
  const status = conversationFilter();
  const query = new URLSearchParams({ status, q: ui.q.trim() });
  if (more) query.set('cursor', list.cursor);
  try {
    const reply = await api('/api/admin/conversation-page?' + query, 'GET', undefined, AbortSignal.timeout(30000));
    if (conversationList !== list || page() !== 'conversas') return;
    const updatesRows = more || list.pages <= 1 || !quiet;
    const previous = updatesRows ? JSON.stringify(list.items) : null;
    if (more) {
      const key = status ? 'id' : 'contact_id';
      const seen = new Set(list.items.map(item => item[key]));
      list.items = [...list.items, ...reply.items.filter(item => !seen.has(item[key]))];
      list.pages++;
    } else if (updatesRows) {
      list.items = reply.items;
      list.pages = 1;
    }
    if (more || list.pages === 1) list.cursor = reply.next_cursor;
    const countChanged = updateHandoverCount(reply.waiting_count);
    list.busy = false;
    if (!ui.conv && list.items.length && (openFirst || !matchMedia('(max-width: 900px)').matches)) {
      openConversation(list.items[0].id, openFirst);
      return;
    }
    if (!quiet || countChanged || (updatesRows && previous !== JSON.stringify(list.items))) renderConvos();
  } catch (error) {
    if (conversationList === list && page() === 'conversas' && !quiet) {
      list.error = true;
      list.busy = false;
      renderConvos();
    }
  } finally {
    list.busy = false;
    if (list.moreRequested && conversationList === list && page() === 'conversas') {
      list.moreRequested = false;
      void loadConversationPage({more: true});
    }
  }
}

function openConversation(id, mobile = true) {
  ui.conv = id;
  ui.mobileDetail = mobile;
  if (conversationThread?.id !== id) conversationThread = null;
  renderConvos();
  void loadConversationThread();
}

function threadPreview() {
  if (!ui.conv) return null;
  return conversationThread?.conversation || conversationList?.items?.find(item => item.id === ui.conv);
}

async function loadConversationThread({ older = false, quiet = false } = {}) {
  if (!ui.conv) return;
  if (conversationThread?.id !== ui.conv) {
    conversationThread = { id: ui.conv, messages: [], conversation: null, cursor: null, busy: false, error: false };
  }
  const thread = conversationThread;
  if (older && !thread.cursor) return;
  if (thread.busy) {
    if (older) thread.olderRequested = true;
    return;
  }
  thread.busy = true;
  thread.error = false;
  if (older) renderConvos();
  const query = older ? '?' + new URLSearchParams({ cursor: thread.cursor }) : '';
  try {
    const reply = await api('/api/admin/conversations/' + encodeURIComponent(thread.id) + '/history' + query,
                            'GET', undefined, AbortSignal.timeout(30000));
    if (conversationThread !== thread || ui.conv !== thread.id || page() !== 'conversas') return;
    const latest = older ? null : JSON.stringify(reply);
    if (!older && quiet && latest === thread.latest) return;
    if (older) {
      const displayed = new Set(thread.messages.map(item => item.id));
      thread.messages = [...reply.messages.filter(item => !displayed.has(item.id)), ...thread.messages];
      thread.cursor = reply.next_cursor;
    } else {
      thread.latest = latest;
      const latestIds = new Set(reply.messages.map(item => item.id));
      const overlaps = thread.messages.some(item => latestIds.has(item.id));
      if (overlaps) {
        const archived = thread.messages.filter(item => !latestIds.has(item.id));
        thread.messages = [...archived, ...reply.messages];
      } else {
        thread.messages = reply.messages;
        thread.cursor = reply.next_cursor;
      }
      thread.conversation = reply.conversation;
      const list = conversationList;
      const row = list?.items?.find(item => item.id === thread.id);
      const filter = conversationFilter();
      if (row && filter && filter !== reply.conversation.status) {
        list.items = list.items.filter(item => item.id !== thread.id);
      } else if (row) {
        const {status, operator_name, blocked, can_reply, visit_confirmed} = reply.conversation;
        Object.assign(row, {status, operator_name, blocked, can_reply, visit_confirmed});
      }
    }
    thread.busy = false;
    renderConvos(older);
  } catch (error) {
    if (conversationThread === thread && page() === 'conversas' && !quiet) {
      if (error.status === 404) {
        ui.conv = '';
        ui.mobileDetail = false;
        conversationThread = null;
        toast('Conversa não encontrada.');
      } else {
        thread.error = true;
      }
      thread.busy = false;
      renderConvos();
    }
  } finally {
    thread.busy = false;
    if (thread.olderRequested && conversationThread === thread && page() === 'conversas') {
      thread.olderRequested = false;
      void loadConversationThread({older: true});
    }
  }
}

async function refresh() {
  if (!me || page() !== 'conversas' || document.hidden || !conversationList) return;
  const list = conversationList;
  await Promise.allSettled([
    list.items && loadConversationPage({ quiet: true }),
    conversationThread?.conversation && (ui.mobileDetail || !matchMedia('(max-width: 900px)').matches)
      && loadConversationThread({ quiet: true }),
  ]);
}