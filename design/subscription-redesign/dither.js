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

// README 대표 이미지를 밝기 기준 1비트 점묘로 바꾼다. CORS가 막힌 이미지는 흑백 <img>로 대체한다.
const images = new Map();
function paintImage(canvas) {
  const src = canvas.dataset.src;
  if (!images.has(src)) {
    images.set(src, new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    }));
  }
  images.get(src).then(img => {
    const w = canvas.width, h = Math.max(48, Math.min(140, Math.round(w * img.naturalHeight / img.naturalWidth)));
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, w, h);
    const { data } = ctx.getImageData(0, 0, w, h), light = [];
    for (let i = 0; i < data.length; i += 4) light.push((data[i] * 0.3 + data[i + 1] * 0.59 + data[i + 2] * 0.11) / 255 * (data[i + 3] / 255));
    // 밝은 바탕 배너는 반전해 어두운 테마에서 바탕이 점으로 뒤덮이지 않게 한다
    const flip = light.reduce((a, b) => a + b, 0) / light.length > 0.55;
    if (flip) light.forEach((v, i) => { light[i] = 1 - v; });
    const lo = Math.min(...light), span = Math.max(0.05, Math.max(...light) - lo);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text');
    light.forEach((value, i) => {
      const x = i % w, y = Math.floor(i / w);
      if (((value - lo) / span) * 0.9 > BAYER[(y % 4) * 4 + (x % 4)]) ctx.fillRect(x, y, 1, 1);
    });
  }).catch(() => {
    const img = new Image();
    img.className = 'halftone';
    img.alt = '';
    img.onload = () => canvas.replaceWith(img);
    img.onerror = () => { canvas.dataset.dither = 'seed'; canvas.dataset.seed = src; paint(canvas); };
    img.src = src;
  });
}

window.paintDither = (root = document) => root.querySelectorAll('canvas[data-dither]').forEach(c => (c.dataset.dither === 'image' ? paintImage : paint)(c));
