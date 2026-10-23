// TypeSafe식 1비트 디더 그림: <canvas data-dither="orb|burst|logo|compass|bookmark|plus|seed|field" data-seed="저장소명">
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
  // stoic 완료 화면의 꽃잎을 점묘로 옮긴 형태 (알림 단계 삽화)
  burst: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
    const petal = Math.pow(Math.max(0, Math.cos(a * 8)), 3) * 0.42;
    return r < 0.08 ? 1 : r < 0.12 + petal ? 1 - r * 1.6 : 0;
  },
  // 레일 아이콘은 한 문법을 쓴다: 형태를 만드는 선은 꽉 찬 실선(1)이라 언제나 찍히고,
  // 안쪽이나 뒤쪽만 옅은 값으로 두어 점묘 질감을 낸다. 메뉴 아이콘은 20칸이라 실선을 2칸 이상 두께로 잡는다.
  // 서비스 로고(2026-10-23 확정 모양): 굵은 꽃잎을 디더 없이 꽉 채운 실루엣. 20칸 격자 그대로 정수배로만 키운다
  logo: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
    const petal = Math.pow(Math.max(0, Math.cos(a * 8)), 1.2) * 0.36;
    return r < 0.14 || r < 0.12 + petal ? 1 : 0;
  },
  compass: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy);
    const along = (dx - dy) / Math.SQRT2, across = (dx + dy) / Math.SQRT2;
    if (Math.abs(along) < 0.27 && Math.abs(across) < 0.14 * (1 - Math.abs(along) / 0.27)) return along > 0 ? 1 : 0.5;
    if (Math.abs(r - 0.4) < 0.065) return 1;
    return r < 0.34 ? 0.2 + (0.5 - y) * 0.3 : 0;
  },
  bookmark: (x, y) => {
    const inside = m => x > 0.24 + m && x < 0.76 - m && y > 0.07 + m && y < 0.93 - m && y < 0.93 - 0.22 * (1 - Math.abs(x - 0.5) / 0.26) - m * 1.8;
    if (!inside(0)) return 0;
    return inside(0.1) ? 0.6 - (y - 0.07) * 0.45 : 1;
  },
  plus: (x, y) => {
    const dx = Math.abs(x - 0.5), dy = Math.abs(y - 0.5);
    const inside = m => (dx < 0.15 - m && dy < 0.4 - m) || (dy < 0.15 - m && dx < 0.4 - m);
    if (!inside(0)) return 0;
    return inside(0.05) ? 0.5 + (0.5 - y) * 0.4 : 1;
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

function paint(canvas) {
  if (canvas.dataset.dither === 'field') {
    canvas.width = Math.max(1, Math.round(canvas.clientWidth / 3));
    canvas.height = Math.max(1, Math.round(canvas.clientHeight / 3));
  }
  const ctx = canvas.getContext('2d'), { width: w, height: h } = canvas;
  const next = hash(canvas.dataset.seed || ''), rnd = [0.3 + next() * 0.4, 0.3 + next() * 0.4, 1.8 + next() * 0.8];
  const unit = Math.min(w, h), kind = canvas.dataset.dither;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue(canvas.dataset.color || '--text');
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const value = kind === 'field' ? field(x / w, y / h, w / h)
      : shapes[kind]((x - w / 2) / unit + 0.5, (y - h / 2) / unit + 0.5, rnd);
    if (value > BAYER[(y % 4) * 4 + (x % 4)]) ctx.fillRect(x, y, 1, 1);
  }
}

window.paintDither = (root = document) => root.querySelectorAll('canvas[data-dither]').forEach(paint);
