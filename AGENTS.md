# RepoBite 프로젝트 메모리

## Vercel 배포

- Vercel 프로젝트 이름은 `repobite`이고 정식 운영 주소는 `https://repobite.vercel.app`이다.
- `vercel --prod`가 출력한 배포 URL이나 자동 별칭을 정식 운영 주소로 추정하지 않는다. 특히 `https://2026-oss-radar.vercel.app`은 이전 이름의 별칭이며 정식 주소가 아니다.
- 배포 후 `vercel inspect https://repobite.vercel.app`으로 정식 주소가 새 배포 ID를 가리키는지 확인하고, 정식 주소에서 실제 HTML과 `data.json`을 내려받아 변경 내용을 검증한다.
- 일반 `curl`이 Vercel SSO로 리다이렉트되면 공개 배포가 완료됐다고 보고하지 않는다. `vercel curl`은 보호된 배포의 내용 확인에만 사용하고, Deployment Protection 상태는 별도로 명시한다.
