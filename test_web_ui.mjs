// 실행: node test_web_ui.mjs. 사용자 탐색 화면의 읽기 전용 계약 검사.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const html = readFileSync(new URL('./web.html', import.meta.url), 'utf8');
assert.match(html, /data-filter="ai-ml agents-automation"/);
assert.match(html, /id="search"/);
assert.match(html, /id="sort"/);
assert.match(html, /id="clear"/);
assert.match(html, /selected=selected===r\.repo\?'':r\.repo/);
assert.match(html, /a\.href=x\.url/);
assert.match(html, /fetch\('\/data\.json'\)/);
assert.match(html, /opengraph\.githubassets\.com\/1\//);
assert.match(html, /r\.repository_image\|\|social/);
assert.match(html, /img\.className='social'/);
assert.match(html, /\['e',0\],\['m',1\],\['h',2\]/);
assert.doesNotMatch(html, /\/api\/run/);
assert.doesNotMatch(html, /id="collect"/);
assert.doesNotMatch(html, /id="grade"/);
console.log('통과: 탐색·검색·정렬·레포 선택·원본 이슈 이동과 운영 기능 비노출');
