// TypeSafe식 1비트 디더 그림: <canvas data-dither="orb|burst|seed" data-seed="저장소명">
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => (v + 0.5) / 16);

function hash(text) {
  let h = 2166136261;
  for (const c of text) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0) / 4294967296);
}

const shapes = {
  // 왼쪽 위에서 빛을 받는 구
  orb: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy) / 0.42;
    if (r > 1) return 0;
    return Math.max(0, 1 - Math.hypot(x - 0.36, y - 0.32) * 1.9) + 0.12;
  },
  // stoic 완료 화면의 꽃잎을 점묘로 옮긴 형태
  burst: (x, y) => {
    const dx = x - 0.5, dy = y - 0.5, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
    const petal = Math.pow(Math.max(0, Math.cos(a * 8)), 3) * 0.42;
    return r < 0.08 ? 1 : r < 0.12 + petal ? 1 - r * 1.6 : 0;
  },
  // 저장소 이름으로 고정되는 아바타
  seed: (x, y, rnd) => {
    const [cx, cy, s] = rnd;
    return Math.max(0, 1 - Math.hypot(x - cx, y - cy) * s);
  },
};

for (const canvas of document.querySelectorAll('canvas[data-dither]')) {
  const shape = shapes[canvas.dataset.dither], ctx = canvas.getContext('2d');
  const { width: w, height: h } = canvas, next = hash(canvas.dataset.seed || '');
  const rnd = [0.3 + next() * 0.4, 0.3 + next() * 0.4, 1.8 + next() * 0.8];
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text') || '#fff';
  const unit = Math.min(w, h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const u = (x - w / 2) / unit + 0.5, v = (y - h / 2) / unit + 0.5;
    if (shape(u, v, rnd) > BAYER[(y % 4) * 4 + (x % 4)]) ctx.fillRect(x, y, 1, 1);
  }
}
