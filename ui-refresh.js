/* Triage3AM — quiet, pointer-reactive dotted wordmark.
   No libraries, random flicker, auto-scanning animation, or persistent render loop. */
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
        <div class="hero-kicker">Incident response workspace</div>
        <h2 class="hero-title" id="heroTitle">Find the cause,<br><em>not just the error.</em></h2>
        <p class="hero-description">Turn production logs into a focused incident summary, affected services, and practical next steps.</p>
        <div class="hero-bottomline">
          <span class="hero-status">Log analysis</span>
          <span class="hero-note">Root cause · Impact · Response</span>
        </div>
      </div>
      <div class="wordmark-stage">
        <canvas id="wordmarkCanvas" role="img" aria-label="Dotted TRIAGE3AM wordmark. Move the pointer across the letters to highlight the dots." tabindex="0"></canvas>
        <div class="wordmark-caption"><span>TRIAGE3AM</span><span>Incident tooling</span></div>
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
    let frameId = 0;
    let pointer = { x: -1000, y: -1000, active: false };

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

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
      draw();
    }

    function buildPoints() {
      points = [];
      maskCtx.clearRect(0, 0, width, height);
      const label = 'TRIAGE3AM';
      const fontSize = Math.min(width / 9.1, height * 0.58, 78);
      maskCtx.font = `650 ${fontSize}px Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      maskCtx.textAlign = 'center';
      maskCtx.textBaseline = 'middle';
      maskCtx.fillStyle = '#fff';
      maskCtx.fillText(label, width / 2, height / 2 - 2, width * 0.96);

      const image = maskCtx.getImageData(0, 0, mask.width, mask.height);
      const step = clamp(width / 128, 3.4, 5.1);
      for (let y = step; y < height - 3; y += step) {
        for (let x = 2; x < width - 2; x += step) {
          const ix = Math.min(mask.width - 1, Math.floor(x * dpr));
          const iy = Math.min(mask.height - 1, Math.floor(y * dpr));
          const alpha = image.data[(iy * mask.width + ix) * 4 + 3] / 255;
          if (alpha > 0.25) points.push({ x, y, alpha });
        }
      }
    }

    function draw() {
      frameId = 0;
      ctx.clearRect(0, 0, width, height);
      const reach = Math.max(55, Math.min(100, width * 0.16));

      for (const point of points) {
        let influence = 0;
        if (pointer.active) {
          const distance = Math.hypot(point.x - pointer.x, (point.y - pointer.y) * 1.15);
          influence = Math.max(0, 1 - distance / reach);
        }

        const radius = 0.72 + point.alpha * 0.25 + influence * 0.24;
        const alpha = 0.23 + point.alpha * 0.47 + influence * 0.22;
        const r = Math.round(178 + influence * 35);
        const g = Math.round(184 + influence * 8);
        const b = Math.round(171 - influence * 55);
        ctx.beginPath();
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function scheduleDraw() {
      if (frameId) return;
      frameId = window.requestAnimationFrame(draw);
    }

    function setPointer(event) {
      const rect = canvas.getBoundingClientRect();
      pointer = {
        x: clamp(event.clientX - rect.left, 0, width),
        y: clamp(event.clientY - rect.top, 0, height),
        active: true
      };
      scheduleDraw();
    }

    function clearPointer() {
      if (!pointer.active) return;
      pointer.active = false;
      scheduleDraw();
    }

    canvas.addEventListener('pointermove', setPointer, { passive: true });
    canvas.addEventListener('pointerleave', clearPointer);
    canvas.addEventListener('pointerdown', setPointer, { passive: true });
    canvas.addEventListener('focus', () => {
      pointer = { x: width * 0.68, y: height * 0.5, active: true };
      scheduleDraw();
    });
    canvas.addEventListener('blur', clearPointer);

    if ('ResizeObserver' in window) {
      const observer = new ResizeObserver(resize);
      observer.observe(canvas);
    } else {
      window.addEventListener('resize', resize, { passive: true });
    }

    resize();
  }

  function init() {
    addHero();
    initWordmark();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
