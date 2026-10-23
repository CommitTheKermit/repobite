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
  // stoic 완료 화면의 꽃잎을 점묘로 옮긴 형태. 서비스 아이콘으로도 쓴다 (2026-10-23 확정)
  // 작은 실루엣(bold)에서는 꽃잎을 굵게, 가운데를 크게 그려 16px에서도 형태가 남게 한다
  burst: (x, y, rnd, bold) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
    const petal = Math.pow(Math.max(0, Math.cos(a * 8)), bold ? 1.2 : 3) * (bold ? 0.36 : 0.42);
    return r < (bold ? 0.14 : 0.08) ? 1 : r < 0.12 + petal ? 1 - r * 1.6 : 0;
  },
  // 레일 아이콘: 윤곽은 꽉 찬 선(1), 안쪽은 옅은 값으로 두어 디더 점묘가 생기게 한다
  compass: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy);
    const along = (dx - dy) / Math.SQRT2, across = (dx + dy) / Math.SQRT2;
    if (Math.abs(along) < 0.26 && Math.abs(across) < 0.1 * (1 - Math.abs(along) / 0.26)) return along > 0 ? 1 : 0.55;
    if (Math.abs(r - 0.4) < 0.045) return 1;
    return r < 0.36 ? 0.16 + (0.5 - y) * 0.3 : 0;
  },
  bookmark: (x, y) => {
    const inside = m => x > 0.27 + m && x < 0.73 - m && y > 0.12 + m && y < 0.88 - m && y < 0.88 - 0.2 * (1 - Math.abs(x - 0.5) / 0.23) - m * 1.8;
    if (!inside(0)) return 0;
    return inside(0.055) ? 0.75 - (y - 0.12) * 0.75 : 1;
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
const ICONS = { burst: 0 };

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
      : shapes[kind]((x - w / 2) / unit + 0.5, (y - h / 2) / unit + 0.5, rnd, solid);
    if (solid ? value > ICONS[kind] : value > BAYER[(y % 4) * 4 + (x % 4)]) ctx.fillRect(x, y, 1, 1);
  }
}

window.paintDither = (root = document) => root.querySelectorAll('canvas[data-dither]').forEach(paint);
