// RepoBite 연결 프로토타입: 탐색 메인, 4단계 구독 온보딩(분야 > 저장소 > 난이도 > 알림), 내 구독. 저장은 화면 상태로만 흉내 낸다.
const TOPICS = [
  ['ai-ml', 'AI · 머신러닝', 'brain'], ['agents-automation', '에이전트', 'bot'], ['search-knowledge', '검색 · 지식', 'search'],
  ['dev-tools', '개발 도구', 'wrench'], ['web-framework', '웹 프레임워크', 'globe'], ['ui-design-system', 'UI · 디자인', 'palette'],
  ['backend-api', '백엔드 · API', 'server'], ['security-identity', '보안 · 인증', 'shield-check'], ['database', '데이터베이스', 'database'],
  ['ide-terminal', '에디터 · 터미널', 'square-terminal'], ['desktop-app', '데스크톱 앱', 'monitor'], ['observability', '모니터링', 'activity'],
  ['infra-cloud', '인프라', 'cloud'], ['productivity', '생산성', 'list-checks'], ['media-creative', '미디어', 'clapperboard'], ['mobile', '모바일', 'smartphone'],
];
const TOPIC_NAME = Object.fromEntries(TOPICS.map(([key, name]) => [key, name]));
// 화면 난이도 이름은 쉬움·보통·어려움만 쓴다. 판정 기준(본문 충분도)을 난이도 설명으로 노출하지 않는다.
const LEVELS = ['쉬움', '보통', '어려움'];
const EXPERIENCES = [['new', '오픈 소스 기여가 처음입니다', 1], ['project', '프로젝트 개발 경험이 있습니다', 2], ['experienced', '오픈 소스 기여 경험이 있습니다', 3]];
const GROUPS = [['AI', 'ai-ml agents-automation'], ['프레임워크', 'web-framework ui-design-system backend-api'], ['데이터', 'database search-knowledge'],
  ['개발 도구', 'dev-tools ide-terminal testing-quality cicd-release'], ['인프라', 'infra-cloud observability networking-systems'], ['보안', 'security-identity'],
  ['앱', 'desktop-app mobile productivity'], ['미디어', 'media-creative games-graphics']];
const STEPS = [['topics', 'TOPIC'], ['repos', 'REPO'], ['level', 'LV'], ['mail', 'MAIL']];

const repos = new Map();
for (const issue of window.ISSUES) {
  const repo = repos.get(issue.repo) || { name: issue.repo, description: issue.d, topics: new Set(), issues: [] };
  issue.c.forEach(t => repo.topics.add(t));
  repo.issues.push(issue);
  repos.set(issue.repo, repo);
}

const state = { detail: '', dlv: 0, group: '', sort: 'recommended', search: '', onboarded: false, topics: new Set(), subs: new Set(), experience: 'new', level: 1, email: '', consent: true, mail: null, active: '', filter: 1, query: '', error: '' };
const view = document.querySelector('#view'), stack = document.querySelector('#stack');
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const short = name => name.split('/')[1];
const avatar = (name, size = 16, cls = '') => `<canvas class="${cls}" data-dither="seed" data-seed="${esc(name)}" width="${size}" height="${size}" aria-hidden="true"></canvas>`;
const owner = name => `<img class="owner" src="https://avatars.githubusercontent.com/${esc(name.split('/')[0])}?v=4&s=64" alt="" loading="lazy">`;
// 메인과 같은 순서로 저장소 이미지를 고른다: README 대표 이미지 > GitHub 소셜 미리보기 > 저장소 이름
const repoMedia = (name, cls = '') => {
  const social = `https://opengraph.githubassets.com/1/${name}`, image = window.REPO_IMAGES[name] || social;
  return `<span class="card-media ${cls}"><img class="card-art${image === social ? ' social' : ''}" src="${esc(image)}" data-social="${esc(social)}" alt="${esc(name)} 대표 이미지" loading="lazy"><span class="card-fallback" hidden>${esc(name)}</span></span>`;
};
const issues = n => `${n} issue${n === 1 ? '' : 's'}`;
const icon = name => `<span data-lucide="${name}"></span>`;
const subIssues = () => [...state.subs].flatMap(name => repos.get(name).issues);
const route = () => location.hash.replace('#/', '') || 'explore';
const levelTags = list => [1, 2, 3].map(n => [n, list.filter(i => i.lv === n).length]).filter(([, c]) => c).map(([n, c]) => `<span class="tag">${LEVELS[n - 1]} ${c}</span>`).join('');
const issueRow = i => `<a class="issue-row" href="https://github.com/${esc(i.repo)}/issues/${i.n}" target="_blank" rel="noopener noreferrer"><span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">#${i.n}</span><b>${esc(i.t)}</b></a>`;
const go = name => { location.hash = `#/${name}`; };

function flow(step, body, foot) {
  const index = STEPS.findIndex(([key]) => key === step);
  const back = index ? `<button data-go="${STEPS[index - 1][0]}" aria-label="이전">‹</button>` : '<span></span>';
  return `<div class="flow">
    <div class="flow-top">${back}<div class="dashes" aria-label="4단계 중 ${index + 1}단계">${STEPS.map((_, i) => `<span class="${i <= index ? 'on' : ''}"></span>`).join('')}</div><button data-go="explore" aria-label="닫기">×</button></div>
    <div class="panel"><span class="eyebrow">STEP 0${index + 1} / 04</span>${body}</div>
    <div class="flow-foot">${foot}</div></div>`;
}

const screens = {
  explore() {
    const query = state.search.toLowerCase(), groupTopics = state.group.split(' ');
    let list = [...repos.values()].filter(r => (!state.group || [...r.topics].some(t => groupTopics.includes(t))) && (r.name + r.description).toLowerCase().includes(query));
    if (state.sort === 'name') list = list.sort((a, b) => a.name.localeCompare(b.name));
    const chips = [['전체', '']].concat(GROUPS).map(([label, value]) => `<button class="chip" data-group="${value}" aria-pressed="${state.group === value}">${label}${value ? '' : ` <span class="pix">${repos.size}</span>`}</button>`).join('');
    const cards = list.map(r => {
      return `<article class="card win"><button class="card-hit" data-detail="${esc(r.name)}" aria-haspopup="dialog">
        <span class="win-bar"><span>${esc(short(r.name))}</span><span>${issues(r.issues.length)}</span></span>${repoMedia(r.name)}
        <span class="card-body"><span class="card-meta">${owner(r.name)}<span><b>${esc(r.name)}</b><small>${esc(r.description)}</small></span></span><span class="tags">${levelTags(r.issues)}</span></span></button>
</article>`;
    }).join('');
    return `<div class="explore">
      <div class="bar"><select class="sort" id="sort" aria-label="정렬"><option value="recommended">추천순</option><option value="name" ${state.sort === 'name' ? 'selected' : ''}>레포 이름순</option></select><div class="chips">${chips}</div></div>
      <div class="section-head"><span class="eyebrow">REPOSITORIES / ${list.length}</span><button class="ghost" data-go="${state.onboarded ? 'subs' : 'topics'}">${state.onboarded ? '내 구독 보기' : '이슈 알림 구독하기'}</button></div>
      <div class="masonry">${cards || '<p class="empty">일치하는 저장소가 없습니다.</p>'}</div></div>`;
  },
  topics() {
    const tiles = TOPICS.map(([key, name, glyph]) => {
      const count = [...repos.values()].filter(r => r.topics.has(key)).length;
      return `<button class="topic" data-topic="${key}" aria-pressed="${state.topics.has(key)}"><i>${icon(glyph)}</i>${name}<small>${count}</small></button>`;
    }).join('');
    return flow('topics', `<canvas class="art" data-dither="orb" width="84" height="60" aria-hidden="true"></canvas>
      <h1>어떤 분야의 이슈가<br>궁금하세요?</h1><p class="sub">고른 분야의 저장소를 다음 화면에서 보여 드립니다. 숫자는 분야별 저장소 수입니다.</p>
      <div class="topics">${tiles}</div>`,
      `<button class="later" data-go="explore">나중에 할게요</button><button class="next" data-go="repos" aria-label="저장소 선택으로" ${state.topics.size ? '' : 'disabled'}>${icon('arrow-right')}</button>`);
  },
  repos() {
    const query = state.query.toLowerCase();
    const list = [...repos.values()].filter(r => (state.subs.has(r.name) || [...r.topics].some(t => state.topics.has(t))) && r.name.toLowerCase().includes(query));
    const rows = list.map(r => `<button class="repo" data-repo="${esc(r.name)}" aria-pressed="${state.subs.has(r.name)}">${repoMedia(r.name, 'thumb')}<span><b>${esc(r.name)}</b><small>${esc(r.description)}</small></span><span class="pix">${issues(r.issues.length)}</span><span class="check">${icon('check')}</span></button>`).join('');
    return flow('repos', `<h1>어떤 저장소를<br>구독할까요?</h1><p class="sub">${[...state.topics].map(t => TOPIC_NAME[t]).join(', ') || '고른 분야'}의 저장소입니다.</p>
      <input class="search" id="query" type="search" placeholder="저장소 이름으로 찾기" aria-label="저장소 검색" value="${esc(state.query)}">
      <div class="repos">${rows || '<p class="empty">일치하는 저장소가 없습니다.</p>'}</div>`,
      `<button class="later" data-go="topics">분야 다시 고르기</button><button class="next" data-go="level" aria-label="난이도 선택으로" ${state.subs.size ? '' : 'disabled'}>${icon('arrow-right')}</button>`);
  },
  level() {
    const all = subIssues(), matched = all.filter(i => i.lv === state.level);
    const rows = [1, 2, 3].map(n => {
      const count = all.filter(i => i.lv === n).length;
      return `<button class="bench-row" data-level="${n}" aria-pressed="${state.level === n}" style="--at:${all.length ? (count / all.length) * 100 : 0}%"><span class="inv">Lv.${n} ${LEVELS[n - 1]}</span><span></span><span class="count">${count}</span><span class="track"></span></button>`;
    }).join('');
    const first = matched[0];
    const spec = first ? `<div class="spec" style="margin-top:28px;width:100%"><span class="cross tl"></span><span class="cross br"></span>
        <div class="full">${repoMedia(first.repo, 'spec-media')}</div>
        <div><span class="lab">Issue</span><span class="val big">#${first.n}</span></div>
        <div class="right"><span class="outline">Output</span><div class="val" style="margin-top:8px">Lv.${first.lv}</div></div>
        <div class="full"><span class="lab">Repository</span><span class="val">${esc(first.repo)}</span></div>
        <div class="full"><h3>${esc(first.t)}</h3></div>
        <div><span class="lab">Difficulty</span><span class="inv">${LEVELS[first.lv - 1]}</span></div>
        <div class="right"><span class="lab">Match</span><span class="val">${matched.length} / ${all.length}</span></div>
        <div class="full barcode" aria-hidden="true"></div></div>` : '<p class="empty">이 난이도의 이슈가 지금은 없습니다. 새 이슈가 판정되면 보내 드립니다.</p>';
    return flow('level', `<h1>오픈 소스 기여는<br>얼마나 해 보셨어요?</h1><p class="sub">경험에 맞춰 난이도를 추천합니다. 추천은 아래에서 직접 바꿀 수 있습니다.</p>
      <div class="pills" role="group" aria-label="개발 경험">${EXPERIENCES.map(([key, text]) => `<button class="pill" data-exp="${key}" aria-pressed="${state.experience === key}">${text}</button>`).join('')}</div>
      <div class="bench" role="group" aria-label="받을 난이도">${rows}</div>
      <div class="bench-foot" style="width:100%"><div class="circles" aria-label="구독 이슈 ${all.length}건 중 ${matched.length}건">${all.map(i => `<span class="${i.lv === state.level ? 'on' : ''}"></span>`).join('')}</div><span class="pix">${matched.length} / ${issues(all.length)}</span></div>
      ${spec}`,
      `<button class="later" data-go="repos">이전</button><button class="next" data-go="mail" aria-label="알림 설정으로">${icon('arrow-right')}</button>`);
  },
  mail() {
    return flow('mail', `<canvas class="art" data-dither="burst" width="84" height="60" aria-hidden="true"></canvas>
      <h1>새 이슈를 메일로<br>받아 볼까요?</h1><p class="sub">구독한 저장소 ${state.subs.size}곳에서 Lv.${state.level} ${LEVELS[state.level - 1]} 이슈가 생기면 보내 드립니다.</p>
      <div class="slots" aria-hidden="true"><span class="on">1</span><span class="on">2</span><span class="on">3</span></div>
      <div class="slots-cap">하루 최대 3개, 조건에 맞는 이슈가 없으면 보내지 않습니다</div>
      <label class="field-label">알림 이메일<input class="search" id="email" type="email" autocomplete="email" placeholder="you@example.com" value="${esc(state.email)}"></label>
      <div class="toggle-row"><span>선택한 조건의 이슈를 이메일로 받는 데 동의합니다.</span><button class="toggle" data-consent role="switch" aria-checked="${state.consent}" aria-label="이메일 수신 동의"></button></div>
      ${state.error ? `<p class="error" role="alert">${state.error}</p>` : ''}
      <div style="margin-top:28px;display:grid;justify-items:center;gap:4px"><button class="cta" data-finish="mail">알림받기</button><button class="text-btn" data-finish="skip">알림 없이 구독하기</button></div>`, '');
  },
  subs() {
    if (!state.subs.size) {
      return `<div class="page"><header class="page-head"><span class="cross tr"></span><div><span class="eyebrow">MY SUBSCRIPTIONS</span><h1>내 구독</h1></div></header>
        <p class="empty" style="text-align:left">아직 구독한 저장소가 없습니다.</p><button class="solid-btn" data-go="topics">저장소 고르기 ${icon('arrow-right')}</button></div>`;
    }
    if (!state.subs.has(state.active)) state.active = [...state.subs][0];
    const repo = repos.get(state.active), items = repo.issues.filter(i => i.lv === state.filter);
    const cells = items.map(i => `<article><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">#${i.n}</span></div>
      <h3 style="font-size:18px;line-height:1.35;margin:14px 0 12px;letter-spacing:-.01em">${esc(i.t)}</h3>
      <a href="https://github.com/${esc(i.repo)}/issues/${i.n}" target="_blank" rel="noopener noreferrer" style="color:var(--muted);font-size:13px">GitHub에서 열기 ↗</a></article>`).join('');
    return `<div class="page">
      <header class="page-head"><span class="cross tr"></span><div><span class="eyebrow">MY SUBSCRIPTIONS</span><h1>내 구독</h1></div>
        <div style="display:grid;justify-items:end;gap:12px"><span class="pix">${state.subs.size} REPOS / LV.${state.level} / MAIL ${state.mail ? 'ON' : 'OFF'}</span><button class="ghost" data-go="topics">처음부터 다시 설정</button></div></header>
      <nav class="mobile-subs" aria-label="구독 저장소">${[...state.subs].map(n => `<button class="chip" data-active="${esc(n)}" aria-pressed="${n === state.active}">${esc(short(n))}</button>`).join('')}</nav>
      <section class="repo-head">${avatar(repo.name)}<div><h2>${esc(repo.name)}</h2><p>${esc(repo.description)}</p></div><button class="ghost" data-unsub="${esc(repo.name)}">구독 해제</button></section>
      <div class="spec spec-3"><span class="cross tl"></span><span class="cross br"></span>
        <div><span class="lab">Issues</span><span class="val big">${repo.issues.length}</span></div>
        <div><span class="lab">Topics</span><div class="tags" style="margin-top:6px">${[...repo.topics].map(t => `<span class="tag">${esc(TOPIC_NAME[t])}</span>`).join('')}</div></div>
        <div class="right"><span class="lab">Match Lv.${state.filter}</span><div class="circles" style="margin-top:10px">${repo.issues.map(i => `<span class="${i.lv === state.filter ? 'on' : ''}"></span>`).join('')}</div></div>
        <div class="full barcode" aria-hidden="true"></div></div>
      <div class="chips" role="group" aria-label="난이도">${[1, 2, 3].map(n => `<button class="chip" data-filter="${n}" aria-pressed="${state.filter === n}">Lv.${n} ${LEVELS[n - 1]} <span class="pix">${repo.issues.filter(i => i.lv === n).length}</span></button>`).join('')}</div>
      <div class="action-grid">${cells || '<p class="empty" style="text-align:left">이 난이도의 이슈가 지금은 없습니다.</p>'}</div></div>`;
  },
};

function renderSide() {
  stack.classList.remove('stack');
  stack.innerHTML = `<input class="search" id="explore-search" type="search" placeholder="저장소 검색" aria-label="저장소 검색" value="${esc(state.search)}">
    <section class="win dots"><div class="win-bar"><span>RECENT</span><span>${issues(window.ISSUES.length)}</span></div><div class="win-body"><div class="issue-list">${window.ISSUES.slice(0, 6).map(i => `<button class="issue-row with-owner" data-detail="${esc(i.repo)}" aria-haspopup="dialog">${owner(i.repo)}<span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">${esc(short(i.repo))}</span><b>${esc(i.t)}</b></button>`).join('')}</div></div></section>`;
}

// 저장소 상세 다이얼로그: TypeSafe 스펙 시트 오버레이 (2026-10-23 A·B·C 시안 중 C로 확정)
const detailBox = document.querySelector('#detail');
function detailParts(repo) {
  const counts = [1, 2, 3].map(n => repo.issues.filter(i => i.lv === n).length);
  const list = repo.issues.filter(i => !state.dlv || i.lv === state.dlv);
  const subscribed = state.subs.has(repo.name);
  return {
    counts, list,
    topics: `<div class="tags">${[...repo.topics].map(t => `<span class="tag">${esc(TOPIC_NAME[t] || t)}</span>`).join('')}</div>`,
    cta: subscribed ? '<button class="ghost" data-go="subs">구독 중 · 내 구독 보기</button>' : `<button class="solid-btn" data-subscribe="${esc(repo.name)}">이 저장소 구독하기 ${icon('arrow-right')}</button>`,
    github: `<a class="ghost" href="https://github.com/${esc(repo.name)}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>`,
    chips: `<div class="chips" role="group" aria-label="난이도">${[[0, '전체', repo.issues.length], ...counts.map((c, i) => [i + 1, LEVELS[i], c])].map(([n, label, c]) => `<button class="chip" data-dlv="${n}" aria-pressed="${state.dlv === n}">${label} <span class="pix">${c}</span></button>`).join('')}</div>`,
    close: '<button class="detail-close" data-close aria-label="닫기">×</button>',
  };
}
function detailView(repo, p) {
    const cells = p.list.map(i => `<article><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">#${i.n}</span></div>
      <h3 style="font-size:17px;line-height:1.4;margin:12px 0 10px;letter-spacing:-.01em">${esc(i.t)}</h3><a href="https://github.com/${esc(i.repo)}/issues/${i.n}" target="_blank" rel="noopener noreferrer" style="color:var(--muted);font-size:13px">GitHub에서 열기 ↗</a></article>`).join('');
    return `<section class="overlay">${p.close}
      <div class="overlay-top"><div class="overlay-title"><span class="eyebrow">REPOSITORY</span><h2>${esc(short(repo.name))}</h2><span class="card-meta" style="margin-top:16px">${owner(repo.name)}<span><b class="detail-name">${esc(repo.name)}</b><small>${esc(repo.description)}</small></span></span>${p.topics}<div class="overlay-cta">${p.cta}${p.github}</div></div>
        <div class="spec"><span class="cross tl"></span><span class="cross br"></span><div class="full">${repoMedia(repo.name, 'spec-media')}</div>
          <div><span class="lab">Issues</span><span class="val big">${repo.issues.length}</span></div>
          <div class="right"><span class="lab">Topics</span><span class="val big">${repo.topics.size}</span></div>
          ${p.counts.map((c, i) => `<div class="full" style="display:flex;justify-content:space-between"><span class="inv">Lv.${i + 1} ${LEVELS[i]}</span><span class="val">${c}</span></div>`).join('')}
          <div class="full barcode" aria-hidden="true"></div></div></div>
      <div class="overlay-issues">${p.chips}<div class="action-grid">${cells || '<p class="empty" style="text-align:left">이 난이도의 이슈가 지금은 없습니다.</p>'}</div></div></section>`;
}
function renderDetail() {
  const repo = repos.get(state.detail);
  if (!repo) { if (detailBox.open) detailBox.close(); return; }
  detailBox.setAttribute('aria-label', `${repo.name} 상세`);
  detailBox.innerHTML = detailView(repo, detailParts(repo));
  if (!detailBox.open) detailBox.showModal();
  window.lucide.createIcons();
}
detailBox.addEventListener('close', () => { state.detail = ''; });
detailBox.addEventListener('click', event => { if (event.target === detailBox) detailBox.close(); });

function renderStack(name) {
  if (name === 'explore') return renderSide();
  stack.classList.toggle('stack', name !== 'subs');
  if (name === 'subs') {
    stack.innerHTML = state.subs.size ? `<section class="win" style="--i:0"><div class="win-bar"><span>SUBSCRIBED</span><span>${state.subs.size}</span></div><div class="win-body"><div class="sub-list">${[...state.subs].map(n => `<button class="sub-row" data-active="${esc(n)}" aria-current="${n === state.active}">${avatar(n)}<span><b>${esc(short(n))}</b><small>${esc(n.split('/')[0])}</small></span><span class="pix">${repos.get(n).issues.length}</span></button>`).join('')}</div></div></section>
      <section class="win dots" style="--i:1"><div class="win-bar"><span>MAIL</span><span>${state.mail ? 'ON' : 'OFF'}</span></div><div class="win-body"><dl class="kv"><dt>받는 난이도</dt><dd>Lv.${state.level} ${LEVELS[state.level - 1]}</dd><dt>받는 주소</dt><dd>${esc(state.mail || '없음')}</dd><dt>발송</dt><dd>하루 최대 3개</dd></dl><button class="ghost" data-go="level" style="margin-top:16px">알림 설정 바꾸기</button></div></section>` : '';
    return;
  }
  const index = STEPS.findIndex(([key]) => key === name);
  const detail = {
    topics: ['관심 분야', [...state.topics].map(t => TOPIC_NAME[t])],
    repos: [`${state.subs.size}개 저장소 구독`, [...state.subs].map(short)],
    level: [`Lv.${state.level} ${LEVELS[state.level - 1]}`, [EXPERIENCES.find(([key]) => key === state.experience)[1]]],
    mail: [state.consent ? (state.email || '이메일 입력 전') : '알림 없이 구독', ['하루 최대 3개']],
  };
  stack.innerHTML = STEPS.slice(0, index + 1).map(([key, word], i) => {
    const [caption, tags] = detail[key];
    return `<section class="win ${i === index ? '' : 'dots'}" style="--i:${i}"><div class="win-bar"><span>${word}</span><span>0${i + 1}/04</span></div><div class="win-body">
      <span class="wordmark">${key === 'level' ? `LV.${state.level}` : word}</span><p class="caption">${esc(caption)}</p>
      <div class="tags">${tags.length ? tags.map(t => `<span class="tag">${esc(t)}</span>`).join('') : '<span class="pix">NONE</span>'}</div></div></section>`;
  }).join('');
}

function render() {
  let name = route();
  if (!screens[name]) name = 'explore';
  document.querySelectorAll('[data-nav]').forEach(a => a.toggleAttribute('aria-current', a.dataset.nav === (name === 'explore' ? 'explore' : 'subs')));
  if ((name === 'level' || name === 'mail') && !state.subs.size) return go(state.topics.size ? 'repos' : 'topics');
  if (name !== 'explore') state.detail = '';
  renderDetail();
  view.innerHTML = screens[name]();
  renderStack(name);
  window.lucide.createIcons();
  window.paintDither();
}

function dialog(lines, done) {
  const box = document.querySelector('#dialog'), bar = document.querySelector('#dialog-bar');
  document.querySelector('#dialog-text').innerHTML = lines;
  box.hidden = false;
  let percent = 0;
  const timer = setInterval(() => {
    percent = Math.min(100, percent + 7 + Math.random() * 12);
    bar.style.width = `${percent}%`;
    bar.textContent = `${Math.round(percent)}%`;
    if (percent === 100) { clearInterval(timer); setTimeout(() => { box.hidden = true; done(); }, 250); }
  }, 90);
}

document.addEventListener('click', event => {
  const b = event.target.closest('button');
  if (!b || b.disabled) return;
  const d = b.dataset;
  if (d.go) return go(d.go);
  if ('group' in d) state.group = d.group;
  if (d.detail) { state.detail = d.detail; state.dlv = 0; }
  if ('close' in d) return detailBox.close();
  if ('dlv' in d) state.dlv = Number(d.dlv);
  if (d.subscribe) {
    state.subs.add(d.subscribe);
    repos.get(d.subscribe).topics.forEach(t => state.topics.add(t));
    if (!state.onboarded) return go('repos');
    state.active = d.subscribe;
  }
  if (d.topic) state.topics.has(d.topic) ? state.topics.delete(d.topic) : state.topics.add(d.topic);
  if (d.repo) state.subs.has(d.repo) ? state.subs.delete(d.repo) : state.subs.add(d.repo);
  if (d.exp) { state.experience = d.exp; state.level = EXPERIENCES.find(([key]) => key === d.exp)[2]; }
  if (d.level) state.level = Number(d.level);
  if ('consent' in d) state.consent = !state.consent;
  if (d.active) state.active = d.active;
  if (d.filter) state.filter = Number(d.filter);
  if (d.unsub) state.subs.delete(d.unsub);
  if (d.finish) {
    const email = document.querySelector('#email').value.trim();
    state.email = email;
    if (d.finish === 'mail' && !state.consent) { state.error = '이메일로 받으려면 수신 동의를 켜 주세요.'; return render(); }
    if (d.finish === 'mail' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { state.error = '알림을 받을 이메일 주소를 확인해 주세요.'; return render(); }
    state.error = '';
    state.mail = d.finish === 'mail' ? email : null;
    state.onboarded = true;
    state.filter = state.level;
    state.active = [...state.subs].find(n => repos.get(n).issues.some(i => i.lv === state.level)) || '';
    render();
    return dialog('Saving ...<br>Subscriptions, Mail', () => go('subs'));
  }
  render();
});
document.addEventListener('change', event => { if (event.target.id === 'sort') { state.sort = event.target.value; render(); } });
document.addEventListener('input', event => {
  const id = event.target.id;
  if (id === 'email') state.email = event.target.value;
  if (id !== 'query' && id !== 'explore-search') return;
  state[id === 'query' ? 'query' : 'search'] = event.target.value;
  render();
  const input = document.querySelector(`#${id}`);
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
});
// 카드 이미지가 깨지면 소셜 미리보기, 그것도 실패하면 저장소 이름을 보여 준다 (error는 버블링되지 않아 캡처 단계에서 받는다)
document.addEventListener('error', event => {
  const img = event.target;
  if (!img.classList || !img.classList.contains('card-art')) return;
  if (!img.classList.contains('social')) { img.classList.add('social'); img.src = img.dataset.social; return; }
  img.hidden = true;
  img.nextElementSibling.hidden = false;
}, true);
window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); });
window.addEventListener('resize', () => window.paintDither(document.querySelector('.desk')));

render();
dialog('Loading ...<br>Repositories, Issues', () => {});
