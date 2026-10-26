// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_collection_progress_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
const base = process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765';
async function waitUntil(check) {
  const deadline = Date.now()+10000;
  while(!check()) {
    assert(Date.now()<deadline,'모의 API 요청이 제한 시간 안에 도착한다');
    await new Promise(resolve=>setTimeout(resolve,10));
  }
}
(async()=>{
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}}), errors = [];
    page.setDefaultTimeout(10000);
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      const original = window.setInterval;
      window.allowCollectionPoll = false;
      window.setInterval = (callback, delay, ...args)=>delay===5000
        ? original(()=>{if(window.allowCollectionPoll) callback(...args)},100)
        : original(callback,delay,...args);
    });
    const target = 'new/ouroboros', existing = 'existing/repo';
    const history = Array.from({length:8},(_,i)=>`history/repo${i}`), seen = new Set();
    const session = {authenticated:true,user:{id:'10',login:'test'},subscriptions:[...history,existing],
      preferences:{topics:[],difficulty:1,experience:'new',email:'',delivery_enabled:false,onboarding_completed:true}};
    let stage = 'queued', holdStatus = false, holdReadback = false, staleStatus, readback, statusReads = 0, failStatus = false;
    const jobs = ()=>[
      ...history.map(repo=>({repo,stage:'done',attempt:1,completion_id:repo,acknowledged:seen.has(repo)})),
      // 구버전 서버의 snapshot 완료 식별자가 남아 있어도 새 완료로 표시하면 안 된다.
      {repo:existing,stage:'done',attempt:0,completion_id:'legacy-snapshot',acknowledged:false},
      ...(session.subscriptions.includes(target)?[{repo:target,stage,attempt:stage==='queued'?0:1,completion_id:stage==='done'?'target-complete':null,acknowledged:seen.has(target)}]:[]),
    ];
    await page.route('**/api/repos',r=>{
      const collected = [...history,existing,...(stage==='done'?[target]:[])];
      return r.fulfill({json:{subscribed_repos:session.subscriptions,snapshot:{collected_repos:collected,
        items:collected.map((repo,i)=>({repo,number:i+1,title:'이슈',criteria_version:2,grade:{difficulty:1,exclude:false}}))}}});
    });
    await page.route('https://api.github.com/search/**',r=>r.fulfill({json:{items:[{full_name:target,private:false,archived:false,has_issues:true,description:'새 저장소'}]}}));
    await page.route('**/api/account?*',async r=>{
      const request = r.request(), action = new URL(request.url()).searchParams.get('action');
      if(action==='session') {
        if(holdReadback) {holdReadback=false;await new Promise(resolve=>{readback=resolve})}
        return r.fulfill({json:session});
      }
      if(action==='collection') {
        statusReads++;
        const snapshot = jobs();
        if(holdStatus) {holdStatus=false;await new Promise(resolve=>{staleStatus=resolve})}
        if(failStatus) {failStatus=false;return r.fulfill({status:503,json:{error:'일시 조회 실패'}})}
        return r.fulfill({json:{user_id:'10',jobs:snapshot}});
      }
      const body = request.postDataJSON();
      assert.equal(body.expected_user_id,'10');
      if(action==='subscriptions') {
        assert.equal(body.repo,target);
        session.subscriptions.push(target); holdReadback=true;
        return r.fulfill({json:{repo:target,created:true,collection:{repo:target,stage:'queued',attempt:0}}});
      }
      assert.equal(action,'collection_seen');
      seen.add(body.repo);
      return r.fulfill({json:{repo:body.repo,completion_id:body.completion_id,acknowledged:true}});
    });
    await page.goto(base);
    await page.locator('#collection-notices [data-detail="history/repo7"]').waitFor();
    assert.equal(await page.locator(`#toasts [data-detail="${existing}"]`).count(),0,'기존 snapshot은 새 완료 알림을 만들지 않는다');
    await page.waitForTimeout(200);
    holdStatus=true;
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await waitUntil(()=>staleStatus);
    const readsBeforeSubscribe = statusReads;
    await page.locator('.rail [data-external-search]').click();
    await page.locator('#repository-search input').fill('ouroboros');
    await page.locator(`[data-search-repository="${target}"]`).click();
    await page.locator(`[data-subscribe="${target}"]`).click();
    const progress = page.locator(`#collection-progress [data-progress="${target}"]`);
    await progress.waitFor({state:'attached'});
    await waitUntil(()=>readback);
    readback();
    await page.waitForFunction(()=>!document.querySelector('#save-loading').matches(':popover-open'));
    assert.equal(statusReads,readsBeforeSubscribe,'진행 중인 상태 조회와 새 요청을 겹쳐 실행하지 않는다');
    const expectProgressVisible = async width=>{
      await page.setViewportSize({width,height:844});
      await page.locator('#collection-notices').evaluate(el=>{el.scrollTop=el.scrollHeight});
      const bounds = await progress.boundingBox();
      assert(bounds&&bounds.y>=0&&bounds.y+bounds.height<=844,'이전 완료 알림을 스크롤해도 수집 진행 막대가 화면에 남는다');
      assert.equal(await page.locator('#collection-progress [data-collection-view]').count(),0);
      assert.equal(await page.locator('#collection-notices [data-progress]').count(),0);
    };
    for(const width of [1440,390,320]) await expectProgressVisible(width);
    await page.locator('#detail [data-close]').click();
    staleStatus();
    await page.waitForFunction(()=>document.querySelector('#collection-progress').textContent.includes('수집 준비 중'));
    await waitUntil(()=>statusReads>readsBeforeSubscribe);
    assert(statusReads>readsBeforeSubscribe,'구독 전의 늦은 조회 후 새 상태를 다시 읽는다');
    await page.evaluate(()=>{window.allowCollectionPoll=true});
    failStatus=true;
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForTimeout(250);
    assert(await progress.isVisible(),'일시 조회 오류는 수집 진행 표시를 끄지 않는다');
    stage='idle';
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForTimeout(250);
    assert(await progress.isVisible(),'일시적으로 비어 있는 상태도 접수한 수집 표시를 지우지 않는다');
    stage='retrying';
    await page.waitForFunction(()=>document.querySelector('#collection-progress').textContent.includes('계속 시도'));
    await page.waitForTimeout(5500);
    assert(await progress.isVisible(),'5초가 지나도 재시도 중인 수집 표시는 유지한다');
    assert(Number.parseInt(await progress.textContent())<100,'서버 완료 전에 100%가 되지 않는다');
    stage='grading';
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#collection-progress').textContent.includes('난이도를 판정하는 중'));
    await expectProgressVisible(390);
    await page.screenshot({path:'/tmp/repobite-collection-progress.png'});
    await page.evaluate(()=>{window.allowCollectionPoll=true});
    stage='done';
    const done = page.locator(`#collection-notices [data-detail="${target}"]`);
    await done.waitFor();
    await progress.waitFor({state:'detached'});
    assert.equal(await page.locator('#collection-notices .toast').first().locator('[data-detail]').getAttribute('data-detail'),target,'방금 끝난 수집 결과를 기존 완료 목록의 맨 위에 둔다');
    await done.click();
    assert.equal(await page.locator('#detail[open]').getAttribute('aria-label'),`${target} 상세`,'방금 수집한 저장소 상세를 연다');
    assert.equal(await done.count(),0);
    assert.equal(await page.locator('#collection-notices [data-collection-view]').count(),history.length,'다른 레포의 미확인 완료 기록을 보존한다');
    assert.deepEqual(errors,[]);
    console.log('통과: 구독 응답 즉시 진행 표시, 늦은 조회 후 재조회, 오류·idle·재시도·새로고침 중 유지, 기존 결과 알림 제외, 진행·완료 스크롤 분리, 해당 레포 완료·보기');
  } finally {await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
