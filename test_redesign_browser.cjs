// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_redesign_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
(async () => {
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(10000);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    const session={authenticated:true,user:{id:'10',login:'test-user'},subscriptions:[],preferences:{email:'',delivery_enabled:false,topics:[],difficulty:1,experience:'new',onboarding_completed:false}};
    let stage='queued', attempts=0;
    const issue={repo:'owner/repo',number:1,title:'실제 이슈 <script>text only</script>',criteria_version:2,grade:{difficulty:1,exclude:false,reason:'노출 금지 이유'},categories:['dev-tools'],description:'소개'};
    await page.route('**/api/repos',route=>route.fulfill({json:{subscribed_repos:[...session.subscriptions],snapshot:{collected_repos:['owner/repo'],items:[issue]}}}));
    await page.route('**/data.json',route=>route.fulfill({json:{items:[issue],collected_repos:['owner/repo']}}));
    await page.route('https://api.github.com/search/**',route=>route.fulfill({json:{items:[{full_name:'new/repo',private:false,archived:false,has_issues:true,description:'검색 저장소'}]}}));
    await page.route('**/api/account?*',async route=>{
      const request=route.request(),action=new URL(request.url()).searchParams.get('action');
      if(action==='session') return route.fulfill({json:session});
      if(action==='collection') return route.fulfill({json:{user_id:'10',jobs:session.subscriptions.includes('new/repo')?[{repo:'new/repo',stage,attempt:attempts}]:[]}});
      const body=request.postDataJSON();
      assert.equal(body.expected_user_id,'10');
      if(action==='subscriptions') session.subscriptions=request.method()==='DELETE'?session.subscriptions.filter(n=>n!==body.repo):[...new Set([...session.subscriptions,body.repo])];
      if(action==='personalization') Object.assign(session.preferences,{difficulty:body.difficulty,experience:body.experience,topics:body.topics});
      if(action==='onboarding') Object.assign(session.preferences,{email:body.email,delivery_enabled:body.delivery_enabled,onboarding_completed:true});
      return route.fulfill({json:{}});
    });
    await page.goto(process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765');
    await page.waitForSelector('.card');
    for(const width of [1440,1000,390]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    await page.locator('[data-detail="owner/repo"]').first().click();
    assert(await page.locator('#detail').isVisible());
    assert.equal(await page.getByText('노출 금지 이유').count(),0);
    await page.locator('[data-subscribe="owner/repo"]').click();
    await page.waitForSelector('#onboard[open]');
    assert.match(await page.locator('#onboard').innerText(),/STEP 01 \/ 02/);
    await page.locator('#onboard [data-go="mail"]').click();
    await page.waitForSelector('#onboard [data-finish="skip"]');
    assert.equal(await page.locator('#onboard [data-consent]').getAttribute('aria-checked'),'false');
    await page.locator('#onboard [data-finish="skip"]').click();
    await page.waitForFunction(()=>!document.querySelector('#onboard').open);
    assert.equal(session.preferences.onboarding_completed,true);
    assert.match(page.url(),/127\.0\.0\.1:18765\/?$/);
    await page.locator('[data-close]').click().catch(()=>{});
    await page.goto((process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765') + '/#/topics');
    const topic=page.locator('#view [data-topic="dev-tools"]');
    if(await topic.getAttribute('aria-pressed')!=='true') await topic.click();
    await page.locator('#view [data-go="repos"]').click();
    await page.waitForFunction(()=>location.hash==='#/repos');
    await page.locator('#view [data-go="level"]').click();
    await page.waitForFunction(()=>location.hash==='#/level');
    await page.locator('#view [data-go="mail"]').click();
    await page.locator('#view [data-finish="skip"]').click();
    await page.waitForFunction(()=>location.hash==='#/subs');
    for(const width of [1440,1000,390]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    await page.locator('[data-nav="explore"]').click();

    await page.setViewportSize({width:1440,height:900});
    await page.locator('#explore-search').fill('new');
    const input=await page.locator('#explore-search').elementHandle();
    await page.waitForSelector('[data-detail="new/repo"]');
    assert(await input.evaluate(el=>el===document.querySelector('#explore-search')));
    await page.locator('[data-detail="new/repo"]').click();
    await page.locator('[data-subscribe="new/repo"]').click();
    await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('수집 준비 중'));
    stage='retrying';attempts=2;
    await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('계속 시도'),{timeout:10000});
    assert.equal(await page.getByText('3회 시도 후 수집 실패').count(),0);
    stage='failed';attempts=3;
    await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('3회 시도 후 수집 실패'),{timeout:10000});
    assert.deepEqual(errors,[]);
    console.log('통과: 1440/1000/390 넘침 없음, 상세·구독·2단계 저장, 이유 비노출, 입력 유지 검색, 재시도 후 실패 표시');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
