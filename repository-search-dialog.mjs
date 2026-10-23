import { searchRepositories } from './repository-autocomplete.mjs';

/** 수집 범위 밖의 공개 저장소를 찾아 상세로 넘긴다. 검색만으로 구독하지 않는다. */
export function mountRepositorySearchDialog(dialog, {fetcher = fetch, onSelect, delay = 450} = {}) {
  const form = dialog.querySelector('form');
  const input = dialog.querySelector('input');
  const status = dialog.querySelector('[data-search-status]');
  const results = dialog.querySelector('[data-search-results]');
  const loading = dialog.querySelector('[data-search-loading]');
  let timer, controller, revision = 0, composing = false;
  function cancel() {
    clearTimeout(timer); controller?.abort(); revision++;
    loading.hidden = true; results.setAttribute('aria-busy', 'false');
  }
  function clearResults(message) {
    loading.hidden = true; results.replaceChildren(); status.textContent = message;
    results.setAttribute('aria-busy', 'false');
  }
  async function search(ticket) {
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const repositories = await searchRepositories(fetcher, input.value.trim(), controller.signal);
      if (ticket !== revision || !dialog.open) return;
      clearResults(repositories.length ? `공개 저장소 ${repositories.length}곳을 찾았습니다. 선택하면 상세를 볼 수 있습니다.` : '검색 결과가 없습니다. 저장소 이름이나 owner/repo로 다시 검색해 주세요.');
      for (const repo of repositories) {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'repository-search-result';
        button.dataset.searchRepository = repo.full_name;
        const avatar = document.createElement('img');
        avatar.src = 'https://avatars.githubusercontent.com/' + encodeURIComponent(repo.full_name.split('/')[0]) + '?s=64';
        avatar.alt = ''; avatar.loading = 'lazy';
        const text = document.createElement('span');
        const name = document.createElement('b'); name.textContent = repo.full_name;
        const description = document.createElement('small'); description.textContent = repo.description || '설명이 없는 저장소입니다.';
        text.append(name, description);
        const arrow = document.createElement('span'); arrow.textContent = '↗'; arrow.setAttribute('aria-hidden', 'true');
        button.append(avatar, text, arrow);
        button.addEventListener('click', () => { dialog.close(); onSelect(repo); });
        results.append(button);
      }
    } catch (error) {
      if (ticket !== revision || !dialog.open) return;
      clearResults(error.name === 'AbortError' ? '검색 응답이 늦습니다. 다시 검색해 주세요.' : error.message || 'GitHub 연결을 확인하고 다시 검색해 주세요.');
    } finally { clearTimeout(timeout); }
  }
  function changed(immediate = false) {
    cancel();
    if (composing) { clearResults('검색어를 입력해 주세요.'); return; }
    if (input.value.trim().length < 2) { clearResults('저장소 이름을 두 글자 이상 입력해 주세요.'); return; }
    clearResults('');
    loading.hidden = false;
    results.setAttribute('aria-busy', 'true');
    const ticket = revision;
    timer = setTimeout(() => search(ticket), immediate ? 0 : delay);
  }
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.isComposing) { event.preventDefault(); dialog.close(); }
  });
  input.addEventListener('input', () => changed());
  input.addEventListener('compositionstart', () => { composing = true; cancel(); clearResults('검색어를 입력해 주세요.'); });
  input.addEventListener('compositionend', () => { composing = false; changed(); });
  form.addEventListener('submit', event => { event.preventDefault(); changed(true); });
  dialog.querySelector('[data-search-dismiss]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { event.stopPropagation(); if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => { if (!dialog.open) cancel(); });
  dialog.addEventListener('cancel', cancel);
  return {
    open(query = '') {
      input.value = query; composing = false;
      if (!dialog.open) dialog.showModal();
      input.focus(); changed();
    },
  };
}
