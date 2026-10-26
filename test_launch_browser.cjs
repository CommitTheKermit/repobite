// 실행: REPOBITE_PLAYWRIGHT=/외부/node_modules/playwright node test_launch_browser.cjs
const assert = require('node:assert/strict');
const {chromium} = require(process.env.REPOBITE_PLAYWRIGHT || 'playwright');
(async () => {
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}});
    const errors = [], events = [];
    page.on('pageerror', error => errors.push(error.message));
    const issue = (number, repo, day, categories, eligible = true) => ({repo, number, title: `추천 ${number} <script>`, created_at: `2026-10-${day}T00:00:00Z`, criteria_version: 2, categories, description: repo === 'owner/one' ? 'alpha' : 'beta', grade: {difficulty: 1, readiness: 'ready', exclude: false, reason: '숨겨야 할 판정 이유'}, freshness: {eligible}});
    const items = [issue(1, 'owner/one', '25', ['dev-tools']), issue(2, 'owner/two', '26', ['database']), issue(3, 'owner/one', '26', ['dev-tools'], false)];
    await page.route('**/api/account?*', r => r.fulfill({json: {authenticated: false}}));
    await page.route('**/api/repos', r => r.fulfill({json: {subscribed_repos: [], snapshot: {items, collected_repos: ['owner/one', 'owner/two'], collected_at: '2026-10-26T00:00:00Z'}}}));
    await page.route('**/api/events', r => {events.push(r.request().postDataJSON().name); return r.fulfill({status: 204});});
    let feedbackOk = false, feedbackCalls = 0;
    await page.route('**/api/feedback', async r => {feedbackCalls++; await new Promise(resolve => setTimeout(resolve, 100)); return r.fulfill({status: feedbackOk ? 201 : 503, json: feedbackOk ? {message: '완료'} : {error: '다시 시도하세요.'}});});
    await page.route('https://github.com/**', r => r.fulfill({body: '<html>GitHub test</html>', contentType: 'text/html'}));
    await page.goto(process.env.REPOBITE_TEST_URL || 'http://127.0.0.1:18765');
    await page.locator('.shell:not([inert])').waitFor();
    assert.equal(await page.locator('#featured .featured-row').count(), 2);
    assert.equal(await page.locator('#featured .featured-row a').first().textContent(), '#2 추천 2 <script>');
    assert.equal(await page.getByText('숨겨야 할 판정 이유').count(), 0);
    assert.equal(events.filter(n => n === 'visit').length, 1);
    for (const width of [1440, 1000, 767, 390, 320]) {
      await page.setViewportSize({width, height: 900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width, `overflow at ${width}`);
      await page.locator('.launch-intro h1').scrollIntoViewIfNeeded();
      assert(await page.locator('.launch-intro h1').isVisible());
      const layout = await page.evaluate(() => ({intro: document.querySelector('.launch-intro').getBoundingClientRect().toJSON(), bar: document.querySelector('.bar').getBoundingClientRect().toJSON()}));
      assert(layout.bar.top >= layout.intro.bottom, `intro covered at ${width}`);
      if (width <= 767) assert.equal(Math.round(layout.intro.left), 12);
      await page.getByRole('button', {name: '의견 보내기', exact: true}).click();
      assert(await page.locator('#feedback').isVisible());
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
      await page.getByRole('button', {name: '의견 닫기'}).click();
    }
    await page.setViewportSize({width: 1440, height: 900});
    await page.locator('[data-group="dev-tools ide-terminal testing-quality cicd-release"]').click();
    assert.equal(await page.locator('#featured .featured-row').count(), 1);
    assert.match(await page.locator('#featured h2').textContent(), /1건/);
    await page.locator('[data-group=""]').click();
    await page.locator('#explore-search').fill('missing');
    await page.waitForFunction(() => document.querySelector('#featured h2').textContent.includes('0건'));
    assert.match(await page.locator('#featured').textContent(), /지금은 조건을 통과한 이슈가 없습니다/);
    await page.locator('#explore-search').fill('beta');
    await page.waitForFunction(() => document.querySelector('#featured h2').textContent.includes('1건'));
    await page.locator('#explore-search').fill('');
    const popup = page.waitForEvent('popup');
    await page.locator('#featured a').first().click(); (await popup).close();
    assert.equal(events.filter(n => n === 'featured_click').length, 1);
    await page.locator('.card-hit[data-detail="owner/one"]').click();
    const detailPopup = page.waitForEvent('popup');
    await page.locator('#detail [data-track="issue_click"]').first().click(); (await detailPopup).close();
    assert.equal(events.filter(n => n === 'issue_click').length, 1);
    await page.locator('#detail [data-close]').click();
    await page.getByRole('button', {name: '의견 보내기', exact: true}).click();
    await page.locator('#feedback-text').fill('의견 테스트');
    await page.locator('#feedback [type="submit"]').click();
    assert(await page.locator('#feedback [type="submit"]').isDisabled());
    await page.getByText('다시 시도하세요.', {exact: true}).waitFor();
    assert.equal(await page.locator('#feedback-text').inputValue(), '의견 테스트');
    feedbackOk = true;
    await page.locator('#feedback [type="submit"]').click();
    await page.getByText('의견을 보냈습니다. 고맙습니다.', {exact: true}).waitFor();
    assert.equal(await page.locator('#feedback').isVisible(), false); assert.equal(feedbackCalls, 2);
    await page.reload(); await page.locator('.shell:not([inert])').waitFor();
    assert.equal(events.filter(n => n === 'visit').length, 1);
    assert.deepEqual(errors, []);
    if (!process.env.REPOBITE_TEST_URL) {
      const local = await browser.newPage({viewport: {width: 390, height: 900}});
      const localErrors = []; local.on('pageerror', error => localErrors.push(error.message));
      await local.goto('http://127.0.0.1:18765', {waitUntil: 'domcontentloaded'});
      await local.locator('.shell:not([inert])').waitFor();
      assert(await local.locator('.launch-intro h1').isVisible());
      await local.getByRole('button', {name: '의견 보내기', exact: true}).click();
      await local.locator('#feedback-text').fill('로컬 실패 확인');
      await local.locator('#feedback [type="submit"]').click();
      await local.waitForFunction(() => !document.querySelector('#feedback [type="submit"]').disabled);
      assert.equal(await local.locator('#feedback-text').inputValue(), '로컬 실패 확인');
      assert.equal(await local.locator('[data-feedback-status]').textContent(), '로컬 웹 화면에서 실행하세요.');
      assert.deepEqual(localErrors, []);
      await local.close();
    }
    console.log(JSON.stringify({viewports: [1440,1000,767,390,320], events, feedbackCalls, errors}));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
