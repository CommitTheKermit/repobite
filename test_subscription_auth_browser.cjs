// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_subscription_auth_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
const base = process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765';
const draftKey = 'repobite:redesign-draft:v1';
(async () => {
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    async function fixture(authenticated = false) {
      const context = await browser.newContext();
      const page = await context.newPage();
      const errors = [], writes = [];
      page.on('pageerror', e => errors.push(e.message));
      let loginCalls = 0;
      const failures = {};
      const session = {authenticated,user:{id:'10',login:'test'},subscriptions:[],preferences:{email:'',delivery_enabled:false,topics:[],difficulty:1,experience:'new',onboarding_completed:false}};
      const names = ['owner/repo','second/repo','existing/repo'];
      const snapshot = {collected_repos:names,items:names.map((repo,i)=>({repo,number:i+1,title:'이슈',criteria_version:2,grade:{difficulty:1,exclude:false},categories:['dev-tools']}))};
      await page.route('**/api/repos', r=>r.fulfill({json:{snapshot,subscribed_repos:session.subscriptions}}));
      await page.route('https://api.github.com/search/**', r=>r.fulfill({json:{items:[{full_name:'external/repo',private:false,archived:false,has_issues:true,description:'외부 저장소'}]}}));
      await page.route('**/api/account?*', async r => {
        const request = r.request(), action = new URL(request.url()).searchParams.get('action');
        if (action === 'start') { loginCalls++; return r.fulfill({contentType:'text/html',body:'격리된 로그인 진입점'}); }
        if (action === 'session') return r.fulfill({json:session.authenticated ? session : {authenticated:false}});
        if (action === 'collection') return r.fulfill({json:{user_id:'10',jobs:[]}});
        const body = request.postDataJSON();
        assert(session.authenticated, '로그인 전 쓰기를 호출하지 않는다');
        assert.equal(body.expected_user_id,'10');
        writes.push({action,method:request.method(),body,loading:await page.locator('#save-loading').evaluate(el=>el.matches(':popover-open'))});
        await new Promise(resolve=>setTimeout(resolve,60));
        if (action === 'subscriptions' && failures.repo === body.repo) {
          failures.repo = ''; return r.fulfill({status:503,json:{error:'구독 저장 연결 오류'}});
        }
        if (action === 'personalization' && failures.expired) {
          failures.expired = false; return r.fulfill({status:401,json:{error:'로그인이 필요합니다.'}});
        }
        if (action === 'subscriptions') session.subscriptions = request.method() === 'DELETE' ? session.subscriptions.filter(n=>n!==body.repo) : [...new Set([...session.subscriptions,body.repo])];
        if (action === 'personalization') Object.assign(session.preferences,{difficulty:body.difficulty,experience:body.experience,topics:body.topics});
        if (action === 'onboarding') Object.assign(session.preferences,{email:body.email,delivery_enabled:body.delivery_enabled,onboarding_completed:true});
        return r.fulfill({json:{}});
      });
      async function open(path = '') {
        await page.goto(base + path);
        await page.waitForSelector('#page-loading[hidden]',{state:'attached'});
        await page.evaluate(()=>document.fonts.ready);
      }
      return {page,context,session,errors,writes,failures,open,get loginCalls(){return loginCalls}};
    }
    for (const entry of ['', '/#/subs']) {
      const f = await fixture(); await f.open(entry);
      await f.page.locator('[data-login]').click();
      await f.page.waitForURL('**/api/account?action=start');
      f.session.authenticated = true;
      // 실제 OAuth callback의 신규 계정 목적지. 메인에서 저장한 탐색 경로가 덮어쓰면 안 된다.
      await f.open('/#/topics');
      assert.equal(new URL(f.page.url()).hash,'#/topics','첫 로그인은 전체 온보딩으로 진입한다');
      await f.page.locator('[data-nav="explore"]').click();
      assert.equal(await f.page.locator('.section-head .ghost.invert').innerText(),'레포바이트 이용하기');
      await f.page.locator('.section-head .ghost.invert').click();
      assert.equal(new URL(f.page.url()).hash,'#/topics');
      f.session.preferences.onboarding_completed = true;
      await f.open();
      assert.equal(await f.page.locator('.section-head .ghost.invert').innerText(),'레포바이트 이용하기','온보딩 완료 계정도 같은 메인 버튼을 유지한다');
      await f.page.locator('.section-head .ghost.invert').click();
      assert.equal(new URL(f.page.url()).hash,'#/topics');
      assert.deepEqual(f.errors,[]); await f.context.close();
    }
    for (const entry of ['explore','add']) {
      const f = await fixture(); await f.open();
      if (entry === 'add') {
        await f.page.locator('.rail-add').click();
        await f.page.locator('#repository-search input').fill('external');
        await f.page.locator('[data-search-repository="external/repo"]').click();
      } else await f.page.locator('[data-detail="owner/repo"]').first().click();
      const name = entry === 'add' ? 'external/repo' : 'owner/repo';
      await f.page.locator(`[data-subscribe="${name}"]`).click();
      await f.page.waitForURL('**/api/account?action=start');
      assert.equal(f.loginCalls,1); assert.equal(f.writes.length,0);
      assert.equal(await f.page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)).pendingRepo,draftKey),name);
      f.session.authenticated = true;
      await f.open(); await f.page.waitForSelector(`#detail [data-subscribe="${name}"]`);
      assert.equal(f.writes.length,0,'로그인 복귀만으로 자동 구독하지 않는다');
      await f.page.locator(`[data-subscribe="${name}"]`).click();
      await f.page.waitForSelector('#onboard[open]');
      assert(f.session.subscriptions.includes(name));
      assert.deepEqual(f.errors,[]); await f.context.close();
    }
    {
      const f = await fixture(); await f.open('/#/topics');
      await f.page.locator('[data-topic="dev-tools"]').click();
      await f.page.locator('[data-go="repos"]').click();
      await f.page.locator('#query').fill('external');
      await f.page.locator('[data-repo="external/repo"]').click();
      assert.equal(await f.page.locator('[data-repo="external/repo"]').count(),1,'외부 저장소를 임시 선택해도 검색 결과를 중복 표시하지 않는다');
      await f.page.locator('#query').fill('');
      assert.equal(await f.page.locator('[data-repo="external/repo"]').getAttribute('aria-pressed'),'true');
      assert.equal(f.writes.length,0); assert.equal(f.loginCalls,0);
      assert.deepEqual(f.errors,[]); await f.context.close();
    }
    for (const finish of ['mail','skip']) {
      const f = await fixture(); await f.open('/#/subs');
      await f.page.locator('[data-go="topics"]').click();
      await f.page.locator('[data-topic="dev-tools"]').click();
      await f.page.locator('[data-go="repos"]').click();
      await f.page.locator('[data-repo="owner/repo"]').click();
      await f.page.locator('[data-repo="second/repo"]').click();
      await f.page.locator('[data-repo="second/repo"]').click();
      assert.equal(await f.page.locator('[data-repo="owner/repo"]').getAttribute('aria-pressed'),'true');
      await f.page.locator('[data-go="level"]').click();
      await f.page.locator('[data-exp="project"]').click();
      await f.page.locator('[data-go="mail"]').click();
      await f.page.locator('#email').fill('reader@example.com');
      if (finish === 'mail') await f.page.locator('[data-consent]').click();
      assert.equal(f.loginCalls,0,'2단계 저장소 선택과 알림 화면 진입은 로그인 없이 가능하다');
      assert.equal(f.writes.length,0,'최종 확정 전에는 구독·설정을 저장하지 않는다');
      await f.page.locator(`[data-finish="${finish}"]`).click();
      await f.page.waitForURL('**/api/account?action=start');
      assert.equal(f.loginCalls,1); assert.equal(f.writes.length,0);
      f.session.authenticated = true; f.session.subscriptions = ['existing/repo'];
      await f.open(); await f.page.waitForSelector(`[data-finish="${finish}"]`);
      assert.equal(new URL(f.page.url()).hash,'#/mail');
      assert.equal(await f.page.locator('#email').inputValue(),'reader@example.com');
      assert.equal(await f.page.locator('[data-consent]').getAttribute('aria-checked'),String(finish === 'mail'));
      assert.equal(f.writes.length,0,'로그인 복귀는 선택을 복원하며 자동 저장하지 않는다');
      await f.page.locator(`[data-finish="${finish}"]`).click();
      await f.page.waitForFunction(()=>location.hash==='#/subs');
      assert.deepEqual(f.session.subscriptions.sort(),['existing/repo','owner/repo'],'익명 선택 복원으로 기존 계정 구독을 제거하지 않는다');
      assert.equal(f.session.preferences.difficulty,2);
      assert.equal(f.session.preferences.delivery_enabled,finish === 'mail');
      assert.equal(f.session.preferences.onboarding_completed,true);
      assert.equal(f.writes.filter(w=>w.action==='subscriptions').length,1);
      assert.deepEqual(f.errors,[]); await f.context.close();
    }
    const f = await fixture(true); await f.open('/#/topics');
    await f.page.locator('[data-topic="dev-tools"]').click();
    await f.page.locator('[data-go="repos"]').click();
    await f.page.locator('[data-repo="owner/repo"]').click();
    assert.equal(f.writes.length,0,'로그인한 계정도 온보딩 저장소 선택만으로는 저장하지 않는다');
    await f.page.locator('[data-repo="second/repo"]').click();
    await f.page.locator('[data-go="level"]').click();
    await f.page.locator('[data-go="mail"]').click();
    await f.page.evaluate(()=>{
      window.saveLoadingEvents = [];
      const box = document.querySelector('#save-loading');
      box.addEventListener('beforetoggle', e=>window.saveLoadingEvents.push(e.newState));
    });
    await f.page.locator('[data-finish="skip"]').click();
    await f.page.waitForFunction(()=>location.hash==='#/subs');
    assert.deepEqual(await f.page.evaluate(()=>window.saveLoadingEvents),['open','closed'],'여러 구독·개인화·알림 저장 전체에 로딩을 한 번만 켜고 끈다');
    assert.equal(f.writes.filter(w=>w.action==='subscriptions').length,2);
    assert(f.writes.every(w=>w.loading),'각 구독·개인화·알림 저장 도중 로딩이 유지된다');
    for (const width of [1440,1000,390,320]) {
      await f.page.setViewportSize({width,height:900});
      await f.page.locator('[data-nav="explore"]').click();
      const account = f.page.locator('#account-strip button');
      assert.equal(await account.innerText(),'로그아웃'); assert(await account.isVisible());
      assert.equal(await f.page.locator('.explore-header').count(),0);
      assert.equal(await f.page.getByRole('button',{name:'GitHub 로그인',exact:true}).count(),0);
      assert.equal(await f.page.evaluate(()=>document.documentElement.scrollWidth),width);
      const before = await account.boundingBox();
      await f.page.evaluate(()=>scrollTo(0,1000));
      const after = await account.boundingBox();
      for (const key of ['x','y','width','height']) assert(Math.abs(after[key] - before[key]) < 1,'사이드바 계정 버튼은 스크롤에 고정한다');
      await f.page.evaluate(()=>scrollTo(0,0));
    }
    assert.deepEqual(f.errors,[]); await f.context.close();
    for (const failure of ['partial','expired']) {
      const f = await fixture(true); await f.open('/#/topics');
      await f.page.locator('[data-topic="dev-tools"]').click();
      await f.page.locator('[data-go="repos"]').click();
      await f.page.locator('[data-repo="owner/repo"]').click();
      await f.page.locator('[data-repo="second/repo"]').click();
      await f.page.locator('[data-go="level"]').click();
      await f.page.locator('[data-go="mail"]').click();
      if (failure === 'partial') f.failures.repo = 'second/repo';
      else f.failures.expired = true;
      await f.page.locator('[data-finish="skip"]').click();
      if (failure === 'partial') {
        await f.page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('구독 저장 연결 오류'));
        await f.page.waitForFunction(()=>!document.querySelector('[data-finish="skip"]').disabled);
        assert.equal(new URL(f.page.url()).hash,'#/mail');
        assert.equal(f.session.preferences.onboarding_completed,false);
        assert.deepEqual(f.session.subscriptions,['owner/repo']);
        await f.page.locator('[data-finish="skip"]').click();
      } else {
        await f.page.waitForURL('**/api/account?action=start');
        const draft = await f.page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)),draftKey);
        assert.deepEqual(draft.selection.sort(),['owner/repo','second/repo']);
        assert.equal(draft.owner,'10');
        await f.open();
        await f.page.locator('[data-finish="skip"]').click();
      }
      await f.page.waitForFunction(()=>location.hash==='#/subs');
      assert.equal(f.writes.filter(w=>w.action==='subscriptions'&&w.body.repo==='owner/repo').length,1,'부분 성공한 구독을 재시도에서 중복 저장하지 않는다');
      assert.deepEqual(f.session.subscriptions.sort(),['owner/repo','second/repo']);
      assert.deepEqual(f.errors,[]); await f.context.close();
    }
    console.log('통과: explore/add 구독 로그인, my 선택 무인증·최종 두 버튼 로그인, 복귀 시 선택·설정 복원과 기존 구독 보존, 계정 버튼 위치·문구·고정');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
