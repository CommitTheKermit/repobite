# 수집 저장소의 AI 기여 정책 조사

확인일: 2026-10-26. 대상은 `data.json`(2026-10-23 스냅샷)의 수집 저장소 57개다.
기본 30개 전체와 자동 발굴 8개, 모두 38개를 확인했다. 나머지 발굴 19개는 사용자 요청으로 조사를 중단했다.

## 방법과 한계

- 각 저장소 기본 브랜치의 최신 커밋에서 `CONTRIBUTING*`, `AI_POLICY*`, PR 템플릿, `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `docs/` 아래 기여 문서만 읽었다.
- README, 위키, 외부 문서 사이트, GitHub 저장소 설정(예: PR 생성 권한 제한)은 확인하지 않았다.
- "명시 정책 없음"은 위 파일에서 AI·PR 제한 문구를 찾지 못했다는 뜻이며, AI 기여를 허용한다는 뜻이 아니다.
- 정책은 수시로 바뀐다. pocketbase는 문서에 "일시 중단"이라고 적혀 있다.

## RepoBite 흐름(이슈 → AI 해결 → PR)과의 관계

| 구분 | 저장소 | 내용 |
|---|---|---|
| **외부 PR 불가 또는 사전 승인 필수** | honojs/hono | PR은 메인테이너만 연다. 이슈에 포크 브랜치를 링크하면 메인테이너가 PR을 만든다. 시간을 낭비시키면 AI 사용 여부와 관계없이 닫고 차단할 수 있다. |
| | pocketbase/pocketbase | LLM 스팸으로 PR을 일시 중단했고 기존 협력자만 PR을 열 수 있다. "LLM 기여는 환영하지 않는다." |
| | ghostty-org/ghostty | 처음 기여하는 사람은 "Vouch Request" 토론에서 승인을 받아야 하며, 승인 전 PR은 자동으로 닫힌다. AI 사용은 도구와 범위까지 전부 공개해야 하고, 나쁜 AI 기여자는 공개 차단 목록에 올린다. "주니어라면 AI를 쓰지 말라"고 명시한다. |
| | bookorbit/bookorbit | 승인되고 본인에게 배정된 이슈의 PR만 받고, 나머지는 리뷰 없이 닫는다. AI 사용은 예외 없이 공개해야 한다. |
| **AI 사용 강한 제한** | asciimoo/hister | AI 사용 전부 공개, AI가 주 작성자가 되면 안 됨, 이슈와 PR 설명은 사람이 작성. **good first issue에는 AI를 쓰지 말라**고 명시한다. 슬롭 기여자는 차단한다. |
| | ml-explore/mlx | 에이전트가 사용자를 대신해 PR 생성, push, PR 설명·커밋 메시지 작성, 리뷰 답변을 하면 PR을 닫고 프로젝트에서 차단한다. 사람이 이해하지 못한 버그를 에이전트가 고치는 것도 금지한다. |
| **AI 허용, 공개 필수** | THU-MAIC/OpenMAIC | AI PR 환영. PR에 AI 사용을 표시하고, 리뷰 요청 전에 AI 코드 리뷰를 직접 돌려 지적 사항을 반영해야 한다. |
| | volcengine/OpenViking | PR 템플릿의 "Human Involvement" 항목에서 사람 참여 여부를 정확히 골라야 한다. 작성자는 변경을 설명할 수 있어야 한다. |
| | tt-a1i/archify | 모든 PR에 AI 사용 여부, 도구, 모델, 맡긴 작업을 공개해야 한다. |
| **AI 허용, 책임만 요구** | better-auth/better-auth | AI 기여 환영. 기준과 테스트를 지키고, 제출한 내용을 설명할 수 있어야 한다. |
| | heygen-com/hyperframes | AI 기여 환영, 공개는 필요 없다. 이해하지 못한 코드는 거절한다. |
| **명시 정책 없음** | 나머지 19개 | github-mcp-server, web-llm, needle, vue-vben-admin, astro, reka-ui, dragonfly, semantica, lightpanda, zmx, beszel, microsandbox, AI-Infra-Guard, glance, filebrowser, OpenLogi, openwhispr, BeeCount, VoiceStudio |

명시 정책 없음 저장소에서 확인한 기타 조건:

- dragonflydb/dragonfly, lightpanda-io/browser: 첫 PR에서 CLA 서명이 필요하다.
- semantica-agi/semantica: 이슈에 담당자로 배정될 때까지 기다린 뒤 작업하라고 요청한다.
- Tencent/AI-Infra-Guard, mlc-ai/web-llm: 작은 버그 수정이 아니면 이슈부터 연다.
- astro, reka-ui, dragonfly, lightpanda, microsandbox, OpenLogi, openwhispr, VoiceStudio 등은 `AGENTS.md`나 `CLAUDE.md`를 두고 있다. 에이전트가 저장소에서 작업하는 것을 전제한 지침이며, 외부 기여 정책은 아니다.

## 자동 발굴 저장소 (8개 확인)

| 저장소 | 내용 |
|---|---|
| anomalyco/opencode | AI가 쓴 긴 PR 설명과 이슈는 무시될 수 있다. 자동 검사가 "AI가 쓴 장문"을 표시하면 2시간 안에 고치지 않을 때 닫힌다. 작업 전에 댓글로 배정을 요청한다. |
| morluto/rea | AI 기여 환영. 사람 소유자가 전체 변경을 책임지며, 에이전트가 사람의 검토 확인을 대신 써서는 안 된다. |
| HKUDS/CLI-Anything | 기능 추가는 이슈로 먼저 논의한다. |
| anthropics/claude-plugins-official, ruvnet/ruflo, android/skills, K-Dense-AI/scientific-agent-skills, cursor/plugins | 명시 정책을 찾지 못했다. |

미확인 19개: akitaonrails/ai-memory, NationalSecurityAgency/ghidra, stablyai/orca, Comfy-Org/ComfyUI, codecrafters-io/build-your-own-x, sindresorhus/awesome, public-apis/public-apis, freeCodeCamp/freeCodeCamp, EbookFoundation/free-programming-books, openclaw/openclaw, donnemartin/system-design-primer, nilbuild/developer-roadmap, jwasham/coding-interview-university, obra/superpowers, mattpocock/skills, practical-tutorials/project-based-learning, affaan-m/ECC, NousResearch/hermes-agent, react/react.

## 추가 확인 (수집 목록 밖, 2026-10-26)

| 저장소 | 확인 커밋 | 내용 |
|---|---|---|
| Q00/ouroboros | `05d2718` (2026-10-25) | AI 정책 없음. 새 기능은 이슈로 먼저 논의한다. PR 템플릿에 AI 사용 항목이 없다. `AGENTS.md`·`CLAUDE.md`는 개발용 에이전트 지침이다. 기획서 1절의 기여 사례(PR #2177, #2199)가 나온 저장소다. |
| epoko77-ai/im-not-ai | `b37e020` (2026-10-12) | CONTRIBUTING, AI 정책, PR 템플릿이 없다. `CLAUDE.md`는 유지보수용 에이전트 지침이다. README는 이슈·PR 기여를 받고 기여자를 `CONTRIBUTORS.md`에 기록한다. 사용자 계정의 `CommitTheKermit/im-not-ai`는 이 저장소의 포크(2026-09-22 기준)다. |

## 시사점

1. **추천해도 PR로 이어질 수 없는 저장소가 있다.** hono와 pocketbase는 외부 PR을 받지 않는다. ghostty와 bookorbit는 사전 승인이 없으면 PR이 닫힌다. 이 4곳은 추천에서 빼거나 "PR 전 승인 필요"를 표시해야 한다.
2. **"AI가 PR까지 자동으로" 흐름과 정면으로 충돌하는 곳이 있다.** mlx는 에이전트가 PR을 대신 만들면 차단하고, hister는 good first issue에 AI 사용을 금지한다.
3. **AI 사용 공개를 요구하는 곳이 6곳이다**(ghostty, hister, bookorbit, OpenMAIC, OpenViking, archify). 사용자에게 공개 의무와 형식을 안내해야 한다.
4. 자동 발굴 결과에는 awesome·로드맵·면접 자료 같은 큐레이션 목록 저장소가 여러 개 섞여 있다. 정책과 별개로, 이슈를 코드로 푸는 흐름에 맞는지 따로 검토할 필요가 있다.
5. 판별 단서는 `AI_POLICY.md`, CONTRIBUTING의 "AI Policy/AI Usage" 절, PR 템플릿의 사람 참여 항목, "PR은 메인테이너만", "vouch", "승인과 배정" 같은 문구다. 정책은 바뀌므로 정기 수집 때 다시 확인해야 한다. 분류 작업이라 [할 일](할-일.md)의 Jev 검토와 함께 다룰 수 있다.
