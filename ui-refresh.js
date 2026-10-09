/* Triage3AM — pointer-reactive dotted wordmark. Vanilla JS version for the repo's existing static frontend. */
(() => {
  'use strict';

  function addHero() {
    const main = document.querySelector('.main-container');
    if (!main || document.querySelector('.hero-shell')) return;

    const hero = document.createElement('section');
    hero.className = 'hero-shell';
    hero.setAttribute('aria-labelledby', 'heroTitle');
    hero.innerHTML = `
      <div class="hero-copy">
        <div class="hero-kicker">Incident intelligence / 03:00 AM</div>
        <h2 class="hero-title" id="heroTitle">Find the signal.<br><em>Fix the outage.</em></h2>
        <p class="hero-description">Turn a wall of noisy production logs into a clear root-cause signal, a mapped blast radius, and an actionable first response.</p>
        <div class="hero-bottomline">
          <span class="hero-status">Triage engine ready</span>
          <span class="hero-note">RULE-FREE · EXPLAINABLE · FAST</span>
        </div>
      </div>
      <div class="wordmark-stage">
        <canvas id="wordmarkCanvas" role="img" aria-label="Interactive dotted Triage3AM wordmark. Move your pointer across it to reveal the signal." tabindex="0"></canvas>
        <div class="wordmark-caption"><span>Signal field / 001</span><span>Move pointer to inspect</span></div>
      </div>`;
    main.insertBefore(hero, main.firstChild);
  }

  function initWordmark() {
    const canvas = document.getElementById('wordmarkCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    const mask = document.createElement('canvas');
    const maskCtx = mask.getContext('2d', { willReadFrequently: true });
    if (!maskCtx) return;

    let width = 0;
    let height = 0;
    let dpr = 1;
    let points = [];
    let pointer = { x: -1000, y: -1000, active: false };
    let frameId = 0;
    let lastTime = 0;
    let sweep = 0;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      mask.width = Math.round(width * dpr);
      mask.height = Math.round(height * dpr);
      maskCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildPoints();
    }

    function buildPoints() {
      points = [];
      maskCtx.clearRect(0, 0, width, height);
      const label = 'TRIAGE3AM';
      const fontSize = Math.min(width / 8.7, height * 0.66, 106);
      maskCtx.font = `800 ${fontSize}px "Plus Jakarta Sans", Arial, sans-serif`;
      maskCtx.textAlign = 'center';
      maskCtx.textBaseline = 'middle';
      maskCtx.fillStyle = '#fff';
      maskCtx.fillText(label, width / 2, height / 2 - 2, width * 0.96);
      const image = maskCtx.getImageData(0, 0, mask.width, mask.height);
      const pxStep = Math.max(3.1, Math.min(5.2, width / 140));
      for (let y = pxStep; y < height - 5; y += pxStep) {
        for (let x = 2; x < width - 2; x += pxStep) {
          const ix = Math.min(mask.width - 1, Math.floor(x * dpr));
          const iy = Math.min(mask.height - 1, Math.floor(y * dpr));
          const alpha = image.data[(iy * mask.width + ix) * 4 + 3] / 255;
          if (alpha > 0.2) points.push({ x, y, alpha, phase: Math.random() * Math.PI * 2 });
        }
      }
    }

    function draw(now = 0) {
      frameId = 0;
      const dt = Math.min(.05, lastTime ? (now - lastTime) / 1000 : .016);
      lastTime = now;
      if (!pointer.active && !reducedMotion) sweep = (sweep + dt * Math.max(width * .3, 65)) % (width + 180) - 90;
      ctx.clearRect(0, 0, width, height);

      const px = pointer.active ? pointer.x : sweep;
      const py = pointer.active ? pointer.y : height * .52;
      const reach = Math.max(65, Math.min(145, width * .19));

      // A fine baseline guide and three drifting vector handles echo the reference artwork.
      ctx.save();
      ctx.strokeStyle = 'rgba(117,229,255,.10)';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 7]);
      ctx.beginPath();
      ctx.moveTo(12, height - 22);
      ctx.lineTo(width - 12, height - 22);
      ctx.stroke();
      ctx.restore();

      for (const p of points) {
        const dist = Math.hypot((p.x - px) * .8, p.y - py);
        const influence = Math.max(0, 1 - dist / reach);
        const twinkle = reducedMotion ? 0 : (Math.sin(now * .0015 + p.phase) + 1) * .045;
        const radius = 0.6 + p.alpha * 1.05 + influence * 1.15;
        const alpha = Math.min(.98, .12 + p.alpha * .46 + influence * .67 + twinkle);
        ctx.beginPath();
        ctx.fillStyle = influence > .18 ? `rgba(143,239,255,${alpha})` : `rgba(200,224,255,${alpha})`;
        ctx.arc(p.x, p.y + (reducedMotion ? 0 : Math.sin(now * .00035 + p.phase) * .65), radius, 0, Math.PI * 2);
        ctx.fill();
      }

      // Reveal a soft cyan lens without obscuring the text's dot structure.
      if (!reducedMotion || pointer.active) {
        const glow = ctx.createRadialGradient(px, py, 1, px, py, reach * 1.1);
        glow.addColorStop(0, 'rgba(117,229,255,.11)');
        glow.addColorStop(.55, 'rgba(117,229,255,.035)');
        glow.addColorStop(1, 'rgba(117,229,255,0)');
        ctx.fillStyle = glow;
        ctx.fillRect(Math.max(0, px - reach * 1.1), Math.max(0, py - reach * 1.1), reach * 2.2, reach * 2.2);
      }

      // Pointer-linked corner markers / coordinate-like labels.
      if (pointer.active) {
        const x = Math.max(8, Math.min(width - 8, px));
        const y = Math.max(8, Math.min(height - 30, py));
        ctx.strokeStyle = 'rgba(117,229,255,.5)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x - 6, y); ctx.lineTo(x + 6, y);
        ctx.moveTo(x, y - 6); ctx.lineTo(x, y + 6);
        ctx.stroke();
        ctx.fillStyle = 'rgba(150,224,245,.82)';
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.fillText(`${Math.round(x / width * 100)}, ${Math.round((1 - y / height) * 100)}`, Math.min(width - 52, x + 12), Math.max(12, y - 10));
      }

      if (!reducedMotion || pointer.active) frameId = requestAnimationFrame(draw);
    }

    function setPointer(event) {
      const r = canvas.getBoundingClientRect();
      pointer = { x: event.clientX - r.left, y: event.clientY - r.top, active: true };
      if (!frameId) { lastTime = 0; frameId = requestAnimationFrame(draw); }
    }
    function clearPointer() {
      pointer.active = false;
      if (!frameId) { lastTime = 0; frameId = requestAnimationFrame(draw); }
    }

    canvas.addEventListener('pointermove', setPointer);
    canvas.addEventListener('pointerleave', clearPointer);
    canvas.addEventListener('pointerdown', setPointer);
    canvas.addEventListener('focus', () => { pointer = { x: width * .7, y: height * .5, active: true }; });
    canvas.addEventListener('blur', clearPointer);
    if ('ResizeObserver' in window) new ResizeObserver(resize).observe(canvas);
    else window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && frameId) { cancelAnimationFrame(frameId); frameId = 0; }
      else if (!document.hidden && !frameId) { lastTime = 0; frameId = requestAnimationFrame(draw); }
    });
    resize();
    frameId = requestAnimationFrame(draw);
  }

  function init() { addHero(); initWordmark(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
