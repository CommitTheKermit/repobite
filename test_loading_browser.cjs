// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_loading_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
const base = process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765';
(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const session = {authenticated:true, user:{id:'10',login:'test'}, subscriptions:[], preferences:{topics:[],difficulty:1,experience:'new',email:'',delivery_enabled:false,onboarding_completed:true}};
    let releaseSession, releaseFeed, releaseSearch, releaseSave;
    const sessionGate = new Promise(resolve => releaseSession = resolve);
    const feedGate = new Promise(resolve => releaseFeed = resolve);
    let saveGate = Promise.resolve();
    const issue = {repo:'owner/repo',number:1,title:'이슈',criteria_version:2,grade:{difficulty:1,exclude:false}};
    const snapshot = {collected_repos:['owner/repo'],items:[issue]};
    await page.route('**/api/account?*', async route => {
      const action = new URL(route.request().url()).searchParams.get('action');
      if (action === 'session') { await sessionGate; return route.fulfill({json:session}); }
      if (action === 'collection') return route.fulfill({json:{user_id:'10',jobs:[]}});
      if (action === 'subscriptions') {
        await saveGate;
        session.subscriptions = [route.request().postDataJSON().repo];
        return route.fulfill({json:{}});
      }
      return route.fulfill({json:{}});
    });
    await page.route('**/api/repos', async route => { await feedGate; return route.fulfill({json:{snapshot,subscribed_repos:[]}}); });
    await page.goto(base, {waitUntil:'commit'});
    await page.waitForSelector('#page-loading:not([hidden])');
    assert(await page.locator('.shell').evaluate(el => el.inert));
    releaseSession();
    await page.waitForRequest(r => r.url().endsWith('/api/repos'));
    assert(await page.locator('#page-loading').isVisible(), '피드를 기다리는 동안 첫 진입 로딩을 유지한다');
    await page.waitForTimeout(1200);
    assert.equal(await page.locator('#page-loading .progress span').innerText(),'99%','느린 요청을 완료로 표시하지 않는다');
    await page.evaluate(() => document.fonts.ready);
    const mainLoading = await page.locator('#page-loading .win').boundingBox();
    releaseFeed();
    await page.waitForSelector('.card');
    await page.waitForSelector('#page-loading[hidden]', {state:'attached'});
    assert.equal(await page.locator('.shell').evaluate(el => el.inert), false);

    await page.route('https://api.github.com/search/**', async route => {
      const query = new URL(route.request().url()).searchParams.get('q');
      const gate = new Promise(resolve => releaseSearch = resolve);
      await gate;
      const count = query.startsWith('empty') ? 0 : query.startsWith('many') ? 8 : 1;
      return route.fulfill({json:{items:Array.from({length:count}, (_,i)=>({full_name:`owner/repo${i}`,description:'긴 저장소 설명 '.repeat(30),private:false,archived:false,has_issues:true}))}});
    });
    for (const width of [1440,1000,390,320]) {
      await page.setViewportSize({width,height:844});
      const cta = page.locator('.repository-search-cta');
      assert.equal(await cta.evaluate(el => getComputedStyle(el).textDecorationLine), 'underline');
      if (width < 768) {
        const label = await page.locator('.repository-heading .eyebrow').boundingBox();
        const link = await cta.boundingBox();
        assert(Math.abs(label.y + label.height / 2 - link.y - link.height / 2) < 1, '개수와 GitHub 링크를 한 줄에 표시한다');
        const my = await page.locator('[data-nav="subs"]').boundingBox();
        const add = await page.locator('.rail-add').boundingBox();
        assert(add.x >= my.x + my.width && add.x - my.x - my.width <= 8, 'my 바로 다음에 add를 배치한다');
        assert.equal(await page.locator('.rail-add span').innerText(), 'add');
        assert.equal(await page.locator('.rail [data-search-open]').count(), 1);
        await page.locator('.rail [data-search-open]').click();
        await page.waitForSelector('#explore-search-m');
        await page.locator('[data-search-close]').click();
      }
      await cta.click();
      const dialog = page.locator('#repository-search');
      const input = dialog.getByRole('searchbox');
      const baseline = await dialog.boundingBox();
      const inputTop = (await input.boundingBox()).y;
      assert(await dialog.locator('[data-search-placeholder]').isVisible(), '검색 전 안내와 디더 삽화를 표시한다');
      assert.equal(await dialog.getByText('GitHub의 공개 저장소를 찾아보세요. 구독하면 해당 저장소의 이슈를 바로 수집합니다.').count(),0);
      for (const query of ['single', 'many', 'empty']) {
        const request = page.waitForRequest(r=>r.url().startsWith('https://api.github.com/search/'));
        await input.fill(query);
        await page.waitForSelector('[data-search-loading]:not([hidden])');
        await request;
        assert.equal(await dialog.locator('[data-search-placeholder]').isVisible(), false);
        const windowBox = await page.locator('[data-search-loading] .win').boundingBox();
        const contentBox = await dialog.locator('.repository-search-content').boundingBox();
        assert.equal(await dialog.locator('[data-search-loading]').count(), 1, '검색 로딩은 검색 대화상자 내부에 둔다');
        assert.equal(windowBox.width, Math.min(440, contentBox.width - 24), '검색 영역 안에서 원본 로딩 창 너비를 맞춘다');
        assert.equal(windowBox.height, mainLoading.height, '메인과 같은 로딩 창 높이');
        assert(Math.abs(windowBox.x + windowBox.width / 2 - contentBox.x - contentBox.width / 2) < 1);
        assert(Math.abs(windowBox.y + windowBox.height / 2 - contentBox.y - contentBox.height / 2) < 1, '검색 대화상자의 결과 영역 중앙에 표시한다');
        assert.equal(await dialog.getByText('GitHub에서 공개 저장소를 찾고 있습니다.').count(),0);
        assert.deepEqual(await dialog.boundingBox(),baseline,'검색 중 창의 위치와 크기는 유지한다');
        releaseSearch();
        await page.waitForSelector('[data-search-loading][hidden]', {state:'attached'});
        assert.deepEqual(await dialog.boundingBox(),baseline,'빈 결과·1개·8개 결과에서 창의 위치와 크기는 유지한다');
        assert.equal((await input.boundingBox()).y,inputTop);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
      }
      await input.press('Escape');
    }
    await page.setViewportSize({width:1440,height:900});
    await page.locator('[data-detail="owner/repo"]').first().click();
    saveGate = new Promise(resolve => releaseSave = resolve);
    await page.locator('[data-subscribe="owner/repo"]').click();
    await page.waitForSelector('#save-loading:popover-open');
    releaseSave();
    await page.waitForFunction(()=>!document.querySelector('#save-loading').matches(':popover-open'));
    assert(session.subscriptions.includes('owner/repo'));
    assert.deepEqual(errors,[]);

    // 계정과 공개 API가 실패해도 정적 피드로 진입하고 로딩을 닫는다.
    const fallback = await browser.newPage();
    await fallback.route('**/api/account?*', r=>r.fulfill({status:503,json:{error:'연결 오류'}}));
    await fallback.route('**/api/repos', r=>r.fulfill({status:503,json:{}}));
    await fallback.route('**/data.json', r=>r.fulfill({json:snapshot}));
    await fallback.goto(base, {waitUntil:'domcontentloaded'});
    await fallback.waitForSelector('.card');
    await fallback.waitForSelector('#page-loading[hidden]', {state:'attached'});
    assert.equal(await fallback.locator('#page-loading').isVisible(),false);
    console.log('통과: 실제 요청을 기다리는 진입·저장 로딩, 정적 피드 대체, 4개 폭에서 검색 전·로딩·결과별 창 크기·입력 위치 고정');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
