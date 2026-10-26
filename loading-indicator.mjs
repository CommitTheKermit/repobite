// 원본 HTML의 90ms 퍼센트 애니메이션. 100%는 실제 요청이 끝난 뒤에만 표시한다.
export function mountLoadingIndicator(box, {show = () => { box.hidden = false; }, hide = () => { box.hidden = true; }} = {}) {
  const bar = box.querySelector('.progress span');
  let timer, closing, resolveClosing, generation = 0;
  const draw = percent => {
    bar.style.width = `${percent}%`;
    bar.textContent = `${Math.round(percent)}%`;
  };
  function cancel() {
    generation++;
    clearInterval(timer); clearTimeout(closing);
    resolveClosing?.(); resolveClosing = null;
    hide();
  }
  return {
    start() {
      cancel();
      let percent = 0;
      draw(percent); show();
      timer = setInterval(() => { percent = Math.min(99, percent + 7 + Math.random() * 12); draw(percent); }, 90);
    },
    async finish() {
      const ticket = generation;
      clearInterval(timer); draw(100);
      await new Promise(resolve => { resolveClosing = resolve; closing = setTimeout(resolve, 250); });
      if (ticket === generation) { resolveClosing = null; hide(); }
    },
    cancel,
  };
}
