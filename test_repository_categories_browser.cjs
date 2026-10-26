// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_repository_categories_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
const base = process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765';
(async()=>{
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
    page.setDefaultTimeout(10000);
    page.on('pageerror',error=>errors.push(error.message));
    let categories=['ai-ml','agents-automation'], completed=false, feedReads=0;
    const description='AI 에이전트 워크플로 자동화 도구';
    await page.route('**/api/account?*',r=>{
      const action=new URL(r.request().url()).searchParams.get('action');
      if(action==='session') return r.fulfill({json:{authenticated:true,user:{id:'10',login:'test'},subscriptions:['q00/ouroboros'],preferences:{topics:[],difficulty:1,experience:'new',email:'',delivery_enabled:false,onboarding_completed:true}}});
      return r.fulfill({json:{user_id:'10',jobs:completed?[{repo:'q00/ouroboros',stage:'done',attempt:1,completion_id:'new-completion',acknowledged:false}]:[]}});
    });
    await page.route('**/api/repos',r=>{feedReads++;return r.fulfill({json:{subscribed_repos:[],snapshot:{
      collected_repos:['q00/ouroboros','empty/agent','mobile/app'],
      repositories:{'q00/ouroboros':{description,categories},
        'empty/agent':{description:'이슈가 없는 AI 에이전트',categories:['agents-automation']},
        'mobile/app':{description:'모바일 앱',categories:['mobile']}},
      items:[{repo:'q00/ouroboros',number:1,title:'회귀 테스트 추가',description,categories,
        criteria_version:2,grade:{difficulty:1,exclude:false}}]
    }}})});
    await page.goto(base);
    await page.locator('[data-detail="q00/ouroboros"]').first().waitFor();
    assert.match(await page.locator('#view').innerText(), /AI 에이전트 워크플로 자동화 도구/);
    assert.equal(await page.getByText('카테고리 미정 레포지토리').count(),0);
    for(const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      await page.locator('[data-group="ai-ml agents-automation"]').click();
      assert.equal(await page.locator('.card').count(),2,'분류 결과로 이슈 0건 저장소까지 AI 필터에 표시한다');
      assert(await page.locator('[data-detail="empty/agent"]').first().isVisible());
      assert.equal(await page.locator('[data-detail="mobile/app"]').count(),0);
      await page.locator('[data-detail="q00/ouroboros"]').first().click();
      assert.match(await page.locator('#detail').innerText(), /AI · 머신러닝/);
      assert.match(await page.locator('#detail').innerText(), /에이전트/);
      await page.locator('#detail [data-close]').click();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    // 같은 페이지에서 새 피드를 읽을 때 이전 카테고리가 누적되지 않아야 한다.
    categories=['dev-tools'];
    completed=true;
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await page.locator('#collection-notices [data-detail="q00/ouroboros"]').waitFor();
    assert(feedReads>=2,'같은 페이지에서 새 피드를 다시 읽는다');
    assert.equal(await page.locator('.card [data-detail="q00/ouroboros"]').count(),0);
    assert.equal(await page.locator('.card [data-detail="empty/agent"]').count(),1);
    assert.deepEqual(errors,[]);
    console.log('통과: 자동 분류 설명·상세 태그·AI 필터·이슈 0건·모바일 표시');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
