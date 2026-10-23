import { mountRepositoryAutocomplete } from './repository-autocomplete.mjs';
/** 계정 UI는 공개 피드와 독립적으로 동작하고 저장 결과는 세션 재조회로 확인한다. */
const DRAFT_KEY = 'repobite:account-draft:v1';
const LOGIN_URL = '/api/account?action=start';

function browserStorage() {
  try { return globalThis.sessionStorage; } catch { return null; }
}

class AccountError extends Error {
  constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; }
}

function sessionValue(value) {
  if (value?.authenticated === false) return { authenticated: false, subscriptions: [] };
  if (value?.authenticated !== true || typeof value.user?.id !== 'string'
      || typeof value.user?.login !== 'string' || !Array.isArray(value.subscriptions)
      || !value.subscriptions.every(repo => typeof repo === 'string')
      || typeof value.preferences?.email !== 'string'
      || typeof value.preferences?.delivery_enabled !== 'boolean') {
    throw new AccountError('계정 정보를 확인하지 못했습니다. 잠시 후 다시 시도하세요.');
  }
  return value;
}

/** 필수 마크업 ID는 account-* 계약을 따른다. API 실패는 공개 탐색 상태를 건드리지 않는다. */
export function mountAccountUI({ document, fetch, storage = browserStorage(),
  location = globalThis.location, onSubscriptionsChanged = () => {} }) {
  const ids = ['status', 'login', 'dialog-login', 'open', 'dialog', 'close', 'message',
    'email-form', 'email', 'delivery', 'repo-form', 'repo', 'subscriptions', 'logout'];
  const el = Object.fromEntries(ids.map(id => {
    const node = document.getElementById('account-' + id);
    if (!node) throw new Error('계정 UI 요소가 없습니다: account-' + id);
    return [id, node];
  }));
  const autocomplete = mountRepositoryAutocomplete({ document, input: el.repo, fetch });
  let current = { authenticated: false, subscriptions: [] };
  let revision = 0, busy = false, destroyed = false, emailDirty = false, deliveryDirty = false, repoDirty = false;
  let draftOwnerId = null, draftRestored = false, stateUnknown = false, callbackNoticeShown = false;
  const listeners = [];
  const listen = (node, event, listener) => {
    node.addEventListener(event, listener);
    listeners.push(() => node.removeEventListener(event, listener));
  };
  const active = ticket => !destroyed && ticket === revision;
  const message = text => { el.message.textContent = text; };
  const removeDraft = () => { try { storage?.removeItem(DRAFT_KEY); } catch {} };
  const notify = () => {
    try { onSubscriptionsChanged([...current.subscriptions], {
      authenticated: current.authenticated, user: current.user ? { ...current.user } : null }); } catch {}
  };

  function preserveDraft() {
    const draft = { email: el.email.value, delivery_enabled: el.delivery.checked,
      repo: el.repo.value, owner_id: current.user?.id ?? draftOwnerId,
      dirty: { email: emailDirty, delivery: deliveryDirty, repo: repoDirty } };
    try { storage?.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch {}
  }

  function restoreDraft(userId) {
    if (draftRestored) return;
    draftRestored = true;
    let draft;
    try { draft = JSON.parse(storage?.getItem(DRAFT_KEY) ?? 'null'); } catch {}
    if (!draft || typeof draft.email !== 'string' || typeof draft.repo !== 'string'
        || typeof draft.delivery_enabled !== 'boolean'
        || (draft.owner_id !== null && typeof draft.owner_id !== 'string')) {
      removeDraft(); return;
    }
    if (draft.owner_id && draft.owner_id !== userId) {
      // 다른 GitHub 계정으로 로그인하면 이전 계정 이메일을 새 계정 화면에 복원하지 않는다.
      if (userId) removeDraft();
      return;
    }
    // v1에는 편집 여부가 없어 비어 있지 않은 값만 복원한다. 기본 빈값으로 기존 설정을 가리지 않는다.
    const edited = draft.dirty && typeof draft.dirty === 'object' ? draft.dirty : {
      email: draft.email !== '', delivery: draft.delivery_enabled === true, repo: draft.repo !== ''
    };
    if (!emailDirty && edited.email === true) { el.email.value = draft.email; emailDirty = true; }
    if (!deliveryDirty && edited.delivery === true) { el.delivery.checked = draft.delivery_enabled; deliveryDirty = true; }
    if (!repoDirty && edited.repo === true) { el.repo.value = draft.repo; repoDirty = true; }
    draftOwnerId = draft.owner_id;
    removeDraft();
  }

  function clearPrivateInputs() {
    autocomplete.clear();
    el.email.value = ''; el.delivery.checked = false; el.repo.value = '';
    emailDirty = false; deliveryDirty = false; repoDirty = false; draftOwnerId = null;
    removeDraft();
  }

  function render() {
    const loggedIn = current.authenticated;
    el.status.textContent = stateUnknown ? '계정 연결 확인 필요' : loggedIn ? current.user.login + '님' : '비로그인';
    el.login.hidden = loggedIn; el['dialog-login'].hidden = loggedIn;
    el.logout.hidden = !loggedIn && !stateUnknown; el.logout.disabled = busy;
    el.email.disabled = busy; el.delivery.disabled = busy; el.repo.disabled = busy;
    for (const form of [el['email-form'], el['repo-form']]) {
      for (const button of form.querySelectorAll('button')) button.disabled = busy;
    }
    el.subscriptions.replaceChildren();
    for (const repo of current.subscriptions) {
      const row = document.createElement('li');
      const name = document.createElement('span'); name.textContent = repo;
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = '구독 해지'; remove.disabled = busy;
      remove.setAttribute('aria-label', repo + ' 구독 해지');
      remove.addEventListener('click', () => changeSubscription(repo, true));
      row.append(name, remove); el.subscriptions.append(row);
    }
    if (!current.subscriptions.length) {
      const empty = document.createElement('li');
      empty.textContent = loggedIn ? '구독한 저장소가 없습니다.' : '로그인하면 개인 구독 목록을 볼 수 있습니다.';
      el.subscriptions.append(empty);
    }
  }

  function applySnapshot(snapshot) {
    const previousId = current.user?.id;
    if (snapshot.authenticated && ((previousId && previousId !== snapshot.user.id)
        || (draftOwnerId && draftOwnerId !== snapshot.user.id))) clearPrivateInputs();
    current = snapshot; stateUnknown = false;
    restoreDraft(snapshot.user?.id);
    if (snapshot.authenticated) {
      if (!emailDirty) el.email.value = snapshot.preferences.email;
      if (!deliveryDirty) el.delivery.checked = snapshot.preferences.delivery_enabled;
      draftOwnerId = snapshot.user.id;
    }
    render(); notify();
  }

  async function api(action, method = 'GET', payload) {
    let response;
    try {
      response = await fetch('/api/account?action=' + action, {
        method, credentials: 'same-origin', cache: 'no-store',
        ...(payload === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      });
    } catch { throw new AccountError('계정 서버에 연결하지 못했습니다. 입력을 유지하고 다시 시도하세요.'); }
    let value;
    try { value = await response.json(); }
    catch { throw new AccountError('계정 응답을 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.'); }
    if (!response.ok) {
      throw new AccountError(typeof value?.error === 'string' ? value.error.slice(0, 300)
        : '계정 요청을 처리하지 못했습니다. 입력을 유지하고 다시 시도하세요.', response.status, value?.code);
    }
    return value;
  }

  function open() {
    if (destroyed) return;
    el.dialog.hidden = false;
    if (!el.dialog.open && typeof el.dialog.showModal === 'function') el.dialog.showModal();
  }
  function close() {
    autocomplete.clear();
    if (typeof el.dialog.close === 'function' && el.dialog.open) el.dialog.close();
    else el.dialog.hidden = true;
  }
  function needLogin() {
    open(); message('GitHub 로그인 후 구독과 이메일 설정을 저장할 수 있습니다. 입력은 로그인 후 복원됩니다.');
    return false;
  }
  function fail(error, ticket) {
    if (!active(ticket)) return;
    if (error.status === 401 || (error.status === 409 && error.code === 'account_changed')) {
      current = { authenticated: false, subscriptions: [] };
      notify();
    }
    message(error instanceof AccountError ? error.message : '계정 정보를 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.');
    open();
  }

  async function refresh() {
    if (destroyed) return false;
    const ticket = ++revision; busy = false; render();
    try {
      const snapshot = sessionValue(await api('session'));
      if (!active(ticket)) return false;
      applySnapshot(snapshot);
      if (!callbackNoticeShown && location?.search && new URLSearchParams(location.search).get('auth') === 'failed') {
        callbackNoticeShown = true; open(); message('GitHub 로그인을 완료하지 못했습니다. 입력을 확인하고 다시 로그인하세요.');
      }
      return true;
    } catch (error) {
      if (active(ticket)) {
        stateUnknown = true; render();
        message(error instanceof AccountError ? error.message : '계정 정보를 불러오지 못했습니다.');
      }
      return false;
    }
  }

  async function confirmedMutation(action, method, payload, confirm, success) {
    if (!current.authenticated) return needLogin();
    autocomplete.clear();
    const expectedUser = current.user.id, ticket = ++revision;
    busy = true; message('저장 결과를 확인하고 있습니다.'); render();
    try {
      const result = await api(action, method, { ...payload, expected_user_id: expectedUser });
      if (!active(ticket)) return false;
      const snapshot = sessionValue(await api('session'));
      if (!active(ticket)) return false;
      if (!snapshot.authenticated || snapshot.user.id !== expectedUser) {
        applySnapshot(snapshot);
        throw new AccountError('로그인 계정이 바뀌었습니다. 입력을 확인한 뒤 다시 시도하세요.', 401);
      }
      if (!confirm(snapshot, result)) throw new AccountError('저장 결과를 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.');
      success(snapshot); applySnapshot(snapshot);
      return true;
    } catch (error) { fail(error, ticket); return false; }
    finally { if (active(ticket)) { busy = false; render(); } }
  }

  async function saveEmail(event) {
    event?.preventDefault();
    emailDirty = true; deliveryDirty = true;
    const email = el.email.value, delivery = el.delivery.checked;
    return confirmedMutation('preferences', 'POST', { email, delivery_enabled: delivery },
      (snapshot, result) => typeof result?.preferences?.email === 'string'
        && snapshot.preferences.email === result.preferences.email
        && snapshot.preferences.delivery_enabled === delivery,
      () => { emailDirty = false; deliveryDirty = false; message('이메일 설정을 저장했습니다. 자동 이메일은 발송하지 않습니다.'); });
  }

  async function changeSubscription(repo, remove) {
    if (destroyed) return false;
    if (!current.authenticated || (!remove && !el.repo.value)) {
      el.repo.value = repo; repoDirty = true;
    }
    if (!current.authenticated) return needLogin();
    return confirmedMutation('subscriptions', remove ? 'DELETE' : 'POST', { repo },
      (snapshot, result) => typeof result?.repo === 'string'
        && snapshot.subscriptions.some(name => name.toLowerCase() === result.repo.toLowerCase()) === !remove,
      () => {
        if (!remove && el.repo.value === repo) { el.repo.value = ''; repoDirty = false; }
        message(remove ? '저장소 구독을 해지했습니다.' : '저장소를 구독했습니다.');
      });
  }

  async function logout() {
    if (destroyed) return false;
    const ticket = ++revision;
    clearPrivateInputs(); current = { authenticated: false, subscriptions: [] };
    busy = true; render(); notify();
    try {
      await api('logout', 'POST');
      if (!active(ticket)) return false;
      const snapshot = sessionValue(await api('session'));
      if (!active(ticket)) return false;
      if (snapshot.authenticated) throw new AccountError('로그아웃을 확인하지 못했습니다. 다시 시도하세요.');
      stateUnknown = false; message('로그아웃했습니다.'); return true;
    } catch (error) {
      if (active(ticket)) { stateUnknown = true; fail(error, ticket); }
      return false;
    } finally { if (active(ticket)) { busy = false; render(); } }
  }

  for (const link of [el.login, el['dialog-login']]) {
    link.href = LOGIN_URL;
    listen(link, 'click', preserveDraft);
  }
  listen(el.open, 'click', open);
  listen(el.close, 'click', close);
  listen(el.dialog, 'cancel', event => { event.preventDefault(); close(); });
  listen(el.email, 'input', () => { emailDirty = true; });
  listen(el.delivery, 'change', () => { deliveryDirty = true; });
  listen(el.repo, 'input', () => { repoDirty = true; });
  listen(el['email-form'], 'submit', saveEmail);
  listen(el['repo-form'], 'submit', event => { event.preventDefault(); return changeSubscription(el.repo.value, false); });
  listen(el.logout, 'click', logout);
  render();
  const ready = refresh();
  return { ready, refresh, open, close, logout,
    getState: () => ({ authenticated: current.authenticated, user: current.user ? { ...current.user } : null,
      subscriptions: [...current.subscriptions], busy, stateUnknown }),
    toggleSubscription: repo => changeSubscription(repo, current.subscriptions.some(name => name.toLowerCase() === repo.toLowerCase())),
    destroy() { autocomplete.destroy(); destroyed = true; revision++; listeners.forEach(remove => remove()); clearPrivateInputs(); }
  };
}
