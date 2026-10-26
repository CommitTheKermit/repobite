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
    let stage='queued', attempts=0, githubRequests=0;
    const issue={repo:'owner/repo',number:1,title:'실제 이슈 <script>text only</script>',criteria_version:2,grade:{difficulty:1,exclude:false,reason:'노출 금지 이유'},categories:['dev-tools'],description:'소개'};
    await page.route('**/api/repos',route=>route.fulfill({json:{subscribed_repos:[...session.subscriptions],snapshot:{collected_repos:['owner/repo'],items:[issue]}}}));
    await page.route('**/data.json',route=>route.fulfill({json:{items:[issue],collected_repos:['owner/repo']}}));
    await page.route('https://api.github.com/search/**',route=>{
      githubRequests++;
      const query=new URL(route.request().url()).searchParams.get('q');
      if(query.startsWith('limited')) return route.fulfill({status:429,json:{}});
      return route.fulfill({json:{items:query.startsWith('missing')?[]:[{full_name:'new/repo',private:false,archived:false,has_issues:true,description:'검색 저장소'}]}});
    });
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
    await page.goto(process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765', {waitUntil:'domcontentloaded'});
    await page.waitForSelector('.card');
    for(const width of [1440,1000,390]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
      assert(await page.locator('.repository-search-cta').isVisible());
      assert(await page.locator('.rail [data-external-search]').isVisible());
    }
    await page.locator('.repository-search-cta').click();
    await page.locator('#repository-search [data-search-dismiss]').click();
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
    assert.equal(new URL(page.url()).hash,'','2단계 다이얼로그를 마쳐도 페이지를 옮기지 않는다');
    await page.locator('[data-close]').click().catch(()=>{});
    await page.goto((process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765') + '/#/topics', {waitUntil:'domcontentloaded'});
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
    await page.waitForSelector('#repository-not-found:not([hidden])');
    await page.waitForTimeout(600);
    assert.equal(githubRequests,0,'메인 검색은 수집된 저장소만 검색한다');
    assert(await input.evaluate(el=>el===document.querySelector('#explore-search')));
    await page.locator('#repository-not-found [data-external-search]').click();
    const dialog=page.locator('#repository-search');
    const githubInput=dialog.getByRole('searchbox');
    assert.equal(await githubInput.inputValue(),'new');
    await page.waitForSelector('[data-search-repository="new/repo"]');
    for(const width of [1440,1000,390]) {
      await page.setViewportSize({width,height:900});
      assert(await githubInput.isVisible());
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
      assert.equal(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth),true);
    }
    await githubInput.fill('missing');
    await page.waitForFunction(()=>document.querySelector('[data-search-status]').textContent.includes('검색 결과가 없습니다'));
    await githubInput.fill('limited');
    await page.waitForFunction(()=>document.querySelector('[data-search-status]').textContent.includes('검색 한도'));
    await githubInput.press('Escape');
    await page.waitForFunction(()=>!document.querySelector('#repository-search').open);
    assert.equal(session.subscriptions.includes('new/repo'),false,'검색과 닫기는 구독을 생성하지 않는다');
    await page.setViewportSize({width:1440,height:900});
    await page.locator('#repository-not-found [data-external-search]').click();
    await page.locator('[data-search-repository="new/repo"]').click();
    assert.equal(await dialog.isVisible(),false);
    assert.equal(await page.locator('#detail').isVisible(),true);
    await page.locator('[data-subscribe="new/repo"]').click();
    await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('수집 준비 중'));
    // REPOSITORIES 개수는 검색어와 무관한 전체 수이므로 검색어를 비우고 카드 수와 비교한다.
    const feedState=()=>page.evaluate(()=>{const s=document.querySelector('#explore-search');s.value='';s.dispatchEvent(new Event('input',{bubbles:true}));return {count:Number(document.querySelector('.repository-heading .eyebrow').textContent.split('/')[1]),cards:document.querySelectorAll('.card').length,collecting:!!document.querySelector('#subscribed-feed [data-detail="new/repo"]')};});
    let feed=await feedState();
    assert.equal(feed.collecting,true,'수집 중인 구독 저장소는 탐색 카드로 보인다');
    await page.waitForFunction(()=>Number.parseInt(document.querySelector('#toasts .progress [data-progress="new/repo"]').textContent)>0);
    const toastPercent=Number.parseInt(await page.locator('#toasts .progress [data-progress="new/repo"]').textContent());
    assert(toastPercent>0&&toastPercent<100,'완료 전 진행 막대는 0%보다 크고 100% 미만이다');
    assert.match(await page.locator('#toasts').innerText(),/new\/repo 구독 즉시 수집 · 수집 준비 중/);
    assert.equal(await page.locator('#subscribed-feed .collect-bar [data-progress="new/repo"]').count(),1,'수집 중 카드에도 진행 막대를 그린다');
    assert.equal(feed.count,feed.cards,'수집 중 개수와 카드 수가 같다');
    stage='retrying';attempts=2;
    await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('계속 시도'),{timeout:10000});
    assert.equal(await page.getByText('3회 시도 후 수집 실패').count(),0);
    stage='failed';attempts=3;
    await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('3회 시도 후 수집 실패'),{timeout:10000});
    feed=await feedState();
    assert.equal(feed.collecting,false,'수집 실패한 구독은 탐색 카드에서 빠진다');
    assert.equal(feed.count,feed.cards,'수집 실패 후 개수와 카드 수가 같다');
    await page.locator('[data-close]').click();
    await page.locator('[data-nav="subs"]').click();
    await page.waitForFunction(()=>location.hash==='#/subs');
    await page.locator('.rail [data-external-search]').click();
    await page.locator('#repository-search').getByRole('searchbox').fill('new');
    await page.locator('[data-search-repository="new/repo"]').click();
    await page.waitForFunction(()=>location.hash==='#/explore');
    // 해시 변경 뒤 hashchange 렌더에서 상세가 열리므로 표시될 때까지 기다린다.
    await page.locator('#detail').waitFor();
    assert.deepEqual(errors,[]);
    console.log('통과: 1440/1000/390 넘침 없음, 상세·구독·2단계 저장, 이유 비노출, 수집 범위 검색 격리·외부 검색 대화상자·빈 결과·검색 제한·상세 선택, 재시도 후 실패 표시');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
