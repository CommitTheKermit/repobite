// TypeSafe식 1비트 디더 그림: <canvas data-dither="orb|burst|seed|field" data-seed="저장소명">
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => (v + 0.5) / 16);

function hash(text) {
  let h = 2166136261;
  for (const c of text) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0) / 4294967296);
}

const shapes = {
  // 왼쪽 위에서 빛을 받는 구
  orb: (x, y) => {
    if (Math.hypot(x - 0.5, y - 0.5) > 0.42) return 0;
    return Math.max(0, 1 - Math.hypot(x - 0.36, y - 0.32) * 1.9) + 0.12;
  },
  // stoic 완료 화면의 꽃잎을 점묘로 옮긴 형태
  burst: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
    const petal = Math.pow(Math.max(0, Math.cos(a * 8)), 3) * 0.42;
    return r < 0.08 ? 1 : r < 0.12 + petal ? 1 - r * 1.6 : 0;
  },
  // 서비스 아이콘 시안 A: 레이더 동심원과 탐침
  radar: (x, y) => {
    const r = Math.hypot(x - 0.5, y - 0.5), a = Math.atan2(y - 0.5, x - 0.5);
    if (r < 0.1) return 1;
    if (Math.abs(r - 0.26) < 0.04 || Math.abs(r - 0.42) < 0.04) return 0.9;
    return r < 0.46 && a > -Math.PI / 2 && a < -Math.PI / 6 ? 0.45 * (1 - r) : 0;
  },
  // 서비스 아이콘 시안 B: 한 입 베어 문 구
  bite: (x, y) => {
    if (Math.hypot(x - 0.5, y - 0.5) > 0.42 || Math.hypot(x - 0.84, y - 0.2) < 0.2) return 0;
    return Math.max(0, 1 - Math.hypot(x - 0.36, y - 0.36) * 1.5) + 0.15;
  },
  // 서비스 아이콘 시안 C: 모서리를 베어 문 저장소 블록
  block: (x, y) => {
    if (x < 0.12 || x > 0.88 || y < 0.12 || y > 0.88 || Math.hypot(x - 0.88, y - 0.12) < 0.28) return 0;
    if (x < 0.2 || y > 0.8) return 1;
    return 0.95 - (x + y - 0.24) * 0.5;
  },
  // 저장소 이름으로 고정되는 아바타
  seed: (x, y, [cx, cy, s]) => Math.max(0, 1 - Math.hypot(x - cx, y - cy) * s),
};

// TypeSafe 데스크톱의 언덕 같은 점묘 덩어리 (x, y는 0~1, ar은 가로/세로 비)
const HILLS = [[-0.02, 1.08, 0.4], [0.5, 1.2, 0.36], [1.04, 0.34, 0.3]];
function field(x, y, ar) {
  let v = 0;
  for (const [bx, by, r] of HILLS) v = Math.max(v, 1 - Math.hypot((x - bx) * ar, y - by) / r);
  return Math.pow(Math.max(0, v), 0.9) * 0.95;
}

// 24칸 이하 아이콘은 디더 대신 실루엣으로 그린다. 작은 격자에서는 점 밀도로 회색을 만들 수 없어 윤곽이 흩어진다.
// 레이더는 옅은 탐침 부채꼴이 고리와 엉기지 않도록 진한 부분(고리, 가운데 점)만 남긴다.
const ICONS = { radar: 0.5, bite: 0, block: 0 };

function paint(canvas) {
  if (canvas.dataset.dither === 'field') {
    canvas.width = Math.max(1, Math.round(canvas.clientWidth / 3));
    canvas.height = Math.max(1, Math.round(canvas.clientHeight / 3));
  }
  const ctx = canvas.getContext('2d'), { width: w, height: h } = canvas;
  const next = hash(canvas.dataset.seed || ''), rnd = [0.3 + next() * 0.4, 0.3 + next() * 0.4, 1.8 + next() * 0.8];
  const unit = Math.min(w, h), kind = canvas.dataset.dither, solid = kind in ICONS && unit <= 24;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue(canvas.dataset.color || '--text');
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const value = kind === 'field' ? field(x / w, y / h, w / h)
      : shapes[kind]((x - w / 2) / unit + 0.5, (y - h / 2) / unit + 0.5, rnd);
    if (solid ? value > ICONS[kind] : value > BAYER[(y % 4) * 4 + (x % 4)]) ctx.fillRect(x, y, 1, 1);
  }
}

window.paintDither = (root = document) => root.querySelectorAll('canvas[data-dither]').forEach(paint);
