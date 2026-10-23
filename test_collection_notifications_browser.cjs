// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_collection_notifications_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
const base = process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765';
(async()=>{
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}}), errors = [], writes = [];
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      window.toastToggles = [];
      document.addEventListener('beforetoggle', event=>{if(event.target.id==='toasts') window.toastToggles.push(event.newState)},true);
      const original = window.setInterval;
      window.setInterval = (callback, delay, ...args)=>original(callback,delay===5000?100:delay,...args);
    });
    let userId = '10', failAcknowledgement = false;
    const seen = new Map(), names = ['first/repo','second/repo'];
    const identities = {'first/repo':'a'.repeat(64),'second/repo':'b'.repeat(64)};
    const preferences = {topics:[],difficulty:1,experience:'new',email:'',delivery_enabled:false,onboarding_completed:true};
    await page.route('**/api/repos',r=>r.fulfill({json:{subscribed_repos:names,snapshot:{collected_repos:names,items:names.map((repo,index)=>({repo,number:index+1,title:'이슈',criteria_version:2,grade:{difficulty:1,exclude:false}}))}}}));
    await page.route('**/api/account?*',async r=>{
      const action = new URL(r.request().url()).searchParams.get('action');
      if(action==='session') return r.fulfill({json:{authenticated:true,user:{id:userId,login:'test'+userId},subscriptions:names,preferences}});
      if(action==='collection') return r.fulfill({json:{user_id:userId,jobs:names.map(repo=>({repo,stage:'done',attempt:1,updated_at:'completed',completion_id:identities[repo],acknowledged:seen.get(userId+':'+repo)===identities[repo]}))}});
      assert.equal(action,'collection_seen');
      const body = r.request().postDataJSON(); writes.push(body);
      assert.equal(body.expected_user_id,userId); assert.equal(body.completion_id,identities[body.repo]);
      if(failAcknowledgement) {failAcknowledgement=false;return r.fulfill({status:503,json:{error:'알림 확인 저장 오류'}})}
      seen.set(userId+':'+body.repo,body.completion_id);
      return r.fulfill({json:{repo:body.repo,completion_id:body.completion_id,acknowledged:true}});
    });
    const notice = name=>page.locator(`#toasts [data-detail="${name}"]`);
    await page.goto(base); await notice('second/repo').waitFor();
    await page.waitForTimeout(250);
    const initialToggles = await page.evaluate(()=>window.toastToggles);
    await page.waitForTimeout(5500);
    assert.equal(await page.locator('[data-collection-view]').count(),2,'완료 알림은 5초 후에도 유지하고 조회가 반복돼도 중복 생성하지 않는다');
    assert.deepEqual(await page.evaluate(()=>window.toastToggles),initialToggles,'반복 조회 때 알림을 껐다 켜지 않는다');
    await notice('second/repo').click(); await page.waitForSelector('#detail[open]');
    assert.equal(await notice('second/repo').count(),0);
    assert.equal(await notice('first/repo').count(),1,'확인한 알림만 제거한다');
    await page.locator('[data-close]').click();
    await page.reload(); await notice('first/repo').waitFor();
    assert.equal(await notice('second/repo').count(),0,'새로고침해도 서버의 확인 기록을 적용한다');
    failAcknowledgement = true;
    await notice('first/repo').click(); await page.getByText('알림 확인 저장 오류',{exact:true}).waitFor();
    assert.equal(await notice('first/repo').count(),1,'확인 저장에 실패하면 알림과 재시도를 유지한다');
    assert.equal(await page.locator('#detail[open]').count(),0);
    await notice('first/repo').click(); await page.waitForSelector('#detail[open]');
    await page.locator('[data-close]').click();
    await page.reload(); await page.waitForSelector('#page-loading[hidden]',{state:'attached'});
    await page.waitForTimeout(300); assert.equal(await page.locator('[data-collection-view]').count(),0);
    userId = '20'; await page.reload(); await notice('second/repo').waitFor();
    assert.equal(await page.locator('[data-collection-view]').count(),2,'다른 사용자에게는 확인하지 않은 알림을 표시한다');
    userId = '10'; identities['second/repo'] = 'c'.repeat(64);
    await page.reload(); await notice('second/repo').waitFor();
    assert.equal(await notice('first/repo').count(),0);
    assert.equal(await notice('second/repo').getAttribute('data-collection-view'),identities['second/repo'],'새 수집 완료는 이전 확인과 구분한다');
    assert.equal(writes.length,3); assert.deepEqual(errors,[]);
    console.log('통과: 완료 알림 지속·조회 중복 및 깜박임 없음, 보기 확인 저장·상세 열기·새로고침 유지, 사용자 격리·저장 실패 재시도·새 완료 구분');
  } finally {await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
