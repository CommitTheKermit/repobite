// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_restoration_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
(async () => {
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const session = {authenticated:true,user:{id:'10',login:'test'},subscriptions:['first/repo','second/repo'],preferences:{topics:[],difficulty:2,experience:'project',email:'',delivery_enabled:false,onboarding_completed:false}};
    let feedReads = 0;
    await page.route('**/api/repos', r => {
      feedReads++;
      return r.fulfill({json:{subscribed_repos:session.subscriptions,snapshot:{collected_repos:session.subscriptions,items:session.subscriptions.map((repo,i)=>({repo,number:i+1,title:'이슈 '+i,criteria_version:2,grade:{difficulty:i+1,exclude:false}}))}}});
    });
    await page.route('**/api/account?*', r => {
      const action = new URL(r.request().url()).searchParams.get('action');
      if (action === 'session') return r.fulfill({json:session});
      // 진행 토스트 없이 첫 조회부터 완료된 작업도 피드를 갱신하고 안내해야 한다.
      if (action === 'collection') return r.fulfill({json:{user_id:'10',jobs:[{repo:'second/repo',stage:'done',attempt:1,completion_id:'a'.repeat(64),acknowledged:false}]}});
      const body = r.request().postDataJSON();
      if (action === 'collection_seen') return r.fulfill({json:{repo:body.repo,completion_id:body.completion_id,acknowledged:true}});
      if (action === 'personalization') Object.assign(session.preferences,{difficulty:body.difficulty,experience:body.experience,topics:body.topics});
      if (action === 'onboarding') Object.assign(session.preferences,{email:body.email,delivery_enabled:body.delivery_enabled,onboarding_completed:true});
      return r.fulfill({json:{}});
    });
    await page.goto(process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765');
    const done = page.locator('#toasts [data-detail="second/repo"]');
    await done.waitFor();
    assert.match(await page.locator('#toasts').innerText(), /second\/repo 수집 완료 · 1 issue/);
    assert.equal(feedReads,2);
    await done.click();
    // 보기는 확인 기록 저장이 끝난 뒤 상세를 연다.
    await page.locator('#detail').waitFor();
    await page.locator('[data-close]').click();
    await page.evaluate(()=>{location.hash='#/mail';});
    await page.locator('#view [data-finish="skip"]').click();
    await page.waitForFunction(()=>location.hash==='#/subs');
    assert.equal(await page.locator('.repo-head h2').innerText(),'second/repo','온보딩 후 선택한 난이도의 이슈가 있는 저장소를 연다');
    assert.deepEqual(errors,[]);
    console.log('통과: 첫 조회 완료의 피드 갱신·건수·보기, 온보딩 후 난이도에 맞는 저장소 선택');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
