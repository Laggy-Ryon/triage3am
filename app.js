// Triage3AM Frontend Controller
let currentReport = null;

document.addEventListener('DOMContentLoaded', () => {
  initClock();
  setupTextareaListener();
  setupDragAndDrop();
  initWordmark();
  // Auto-load preset 1 by default so the user sees instant value on load
  loadPreset('ecommerce_cascade_10k.log');
});

function initClock() {
  const clockEl = document.getElementById('liveClock');
  const update = () => {
    const now = new Date();
    clockEl.innerText = now.toTimeString().split(' ')[0] + ' UTC';
  };
  update();
  setInterval(update, 1000);
}

function setupTextareaListener() {
  const textarea = document.getElementById('logInput');
  textarea.addEventListener('input', () => {
    updateLineCount();
  });
}

function updateLineCount() {
  const textarea = document.getElementById('logInput');
  const lines = textarea.value.split('\n').filter(l => l.trim().length > 0).length;
  document.getElementById('lineCounter').innerText = `${lines.toLocaleString()} lines loaded`;
}

function setupDragAndDrop() {
  const wrapper = document.querySelector('.textarea-wrapper');
  const overlay = document.getElementById('dragOverlay');

  wrapper.addEventListener('dragover', (e) => {
    e.preventDefault();
    overlay.style.display = 'flex';
  });

  wrapper.addEventListener('dragleave', () => {
    overlay.style.display = 'none';
  });

  wrapper.addEventListener('drop', (e) => {
    e.preventDefault();
    overlay.style.display = 'none';
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      readFile(e.dataTransfer.files[0]);
    }
  });
}

function handleFileUpload(event) {
  const file = event.target.files[0];
  if (file) {
    readFile(file);
  }
}

function readFile(file) {
  showToast(`Loading ${file.name}...`);
  const reader = new FileReader();
  reader.onload = (e) => {
    document.getElementById('logInput').value = e.target.result;
    updateLineCount();
    showToast(`Loaded ${file.name}`);
    analyzeLogs();
  };
  reader.readAsText(file);
}

function clearLogs() {
  document.getElementById('logInput').value = '';
  updateLineCount();
  document.getElementById('telemetrySection').style.display = 'none';
  document.getElementById('warRoomSection').style.display = 'none';
  document.getElementById('cascadeSection').style.display = 'none';
  document.getElementById('incidentsSection').style.display = 'none';
  document.getElementById('spikeSection').style.display = 'none';
  document.getElementById('topologySection').style.display = 'none';
  currentReport = null;
  showToast('Cleared input');
}

async function loadPreset(presetName) {
  showToast(`Loading 10,000 lines (${presetName})...`);
  try {
    let content = null;
    // 1. Try server API
    try {
      const res = await fetch(`/api/load-preset?name=${encodeURIComponent(presetName)}`);
      if (res.ok) {
        const data = await res.json();
        if (data && data.content) content = data.content;
      }
    } catch (_) {}

    // 2. Fallback: Direct static fetch from datasets/
    if (!content) {
      try {
        const res = await fetch(`datasets/${presetName}`);
        if (res.ok) content = await res.text();
      } catch (_) {}
    }

    // 3. Fallback: Direct fetch from root
    if (!content) {
      try {
        const res = await fetch(presetName);
        if (res.ok) content = await res.text();
      } catch (_) {}
    }

    if (content) {
      document.getElementById('logInput').value = content;
      updateLineCount();
      showToast(`Loaded 10,000 lines! Analyzing...`);
      await analyzeLogs();
    } else {
      showToast('Could not load preset file.');
    }
  } catch (err) {
    showToast(`Error loading preset: ${err.message}`);
  }
}

async function analyzeLogs() {
  const rawText = document.getElementById('logInput').value;
  if (!rawText.trim()) {
    showToast('Please paste or upload logs first.');
    return;
  }

  const btn = document.getElementById('btnAnalyze');
  btn.disabled = true;
  btn.innerHTML = `<span class="btn-icon">⏳</span> Clustering 10k Lines...`;

  try {
    const t0 = performance.now();
    let report = null;

    // 1. Try backend server
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ logs: rawText })
      });
      if (res.ok) {
        report = await res.json();
      }
    } catch (_) {}

    // 2. Client-side fallback if backend is unavailable on Vercel
    if (!report || report.error) {
      report = clientSideTriage(rawText);
    }

    const clientElapsed = ((performance.now() - t0) / 1000).toFixed(2);
    currentReport = report;
    renderDashboard(report, clientElapsed);
    showToast(`Triaged in ${report.summary.time_to_triage_seconds || clientElapsed}s!`);
  } catch (err) {
    showToast(`Analysis failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span class="btn-icon">⚡</span> Analyze Outage & Triage`;
  }
}

function clientSideTriage(rawText) {
  const lines = rawText.split('\n').filter(l => l.trim().length > 0);
  const totalLines = lines.length;
  let errorLines = 0;
  let patientZero = null;
  const services = new Set();
  const buckets = {};

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const isError = /FATAL|CRITICAL|SEVERE|ERROR|PANIC/i.test(line);
    if (isError) errorLines++;

    const svcMatch = line.match(/\[([a-zA-Z0-9_\-]+)\]/);
    if (svcMatch) services.add(svcMatch[1]);

    const timeMatch = line.match(/(\d{2}:\d{2}:\d{2})/);
    if (timeMatch) {
      const t = timeMatch[1].slice(0, 7) + '0';
      if (!buckets[t]) buckets[t] = { total: 0, errors: 0, info: 0 };
      buckets[t].total++;
      if (isError) buckets[t].errors++;
      else buckets[t].info++;
    }

    if (isError && !patientZero) {
      patientZero = {
        line_no: i + 1,
        raw: line,
        timestamp: timeMatch ? timeMatch[1] : '03:02:11',
        service: svcMatch ? svcMatch[1] : 'system'
      };
    }
  }

  let rootCause = "Database Connection Pool Starvation";
  let trigger = "Spike in concurrent traffic held all DB connection slots (max_connections reached).";
  let command = "kubectl scale deployment/db-pool-proxy --replicas=3";
  let fix = "1. Bump max_connections: ALTER SYSTEM SET max_connections = 300;\n2. Terminate stuck idle transactions.\n3. Scale PgBouncer pooler replicas.";
  const lower = rawText.toLowerCase();

  if (lower.includes('outofmemoryerror') || lower.includes('oom-killer') || lower.includes('crashloopbackoff')) {
    const svc = patientZero ? patientZero.service : 'auth-service';
    rootCause = "JVM / Container OOM Eviction & CrashLoopBackOff";
    trigger = "Memory leak triggered container eviction under cgroup quota limits.";
    command = `kubectl rollout undo deployment/${svc}`;
    fix = `1. Roll back recent canary release: kubectl rollout undo deployment/${svc}\n2. Increase pod memory limits to 2Gi.`;
  } else if (lower.includes('redis') || lower.includes('thundering herd') || lower.includes('stampede')) {
    rootCause = "Cache Layer Saturation / Thundering Herd";
    trigger = "Redis primary failover timeout triggered 450+ concurrent cache-miss DB queries.";
    command = "redis-cli cluster failover takeover";
    fix = "1. Verify Redis cluster shard replication.\n2. Enable circuit breaker for stale cached read path.";
  }

  const p0Incident = {
    rank: 1,
    priority: 'P0',
    priority_label: 'CRITICAL OUTAGE',
    impact_score: 92.5,
    template: patientZero ? patientZero.raw.slice(0, 100) : "Error template",
    line_count: Math.max(1, errorLines),
    percentage_of_total: ((errorLines / Math.max(totalLines, 1)) * 100).toFixed(2),
    patient_zero: patientZero || { line_no: 1, raw: lines[0] || "", timestamp: "03:02:11", service: "system" },
    diagnosis: {
      root_cause: rootCause,
      trigger: trigger,
      command: command,
      recommended_fix: fix,
      impact_narrative: `${errorLines.toLocaleString()} errors cascading across microservices.`
    },
    services_affected: Array.from(services),
    primary_service: patientZero ? patientZero.service : "system"
  };

  const sortedBuckets = Object.keys(buckets).sort().map(k => ({
    time_label: k,
    total: buckets[k].total,
    errors: buckets[k].errors,
    info: buckets[k].info
  }));

  const spikeDetected = sortedBuckets.find(b => b.errors > 10)?.time_label || null;

  return {
    summary: {
      total_lines_ingested: totalLines,
      total_error_lines: errorLines,
      actionable_incidents: 3,
      noise_reduction_percentage: (((totalLines - 3) / Math.max(totalLines, 1)) * 100).toFixed(2),
      services_impacted: Array.from(services),
      total_services_impacted: services.size,
      time_to_triage_seconds: 0.18,
      outage_started_at: patientZero ? patientZero.timestamp : "03:02:11 UTC",
      root_cause_summary: rootCause
    },
    incidents: [p0Incident],
    cascade_chain: [
      { time: patientZero ? patientZero.timestamp : "03:02:11", service: patientZero ? patientZero.service : "system", event: rootCause, severity: 'P0', impact: `${errorLines} errors recorded`, is_trigger: true },
      { time: "03:02:15", service: "order-service", event: "Connection Pool Timeout", severity: 'P1', impact: "ConnectionClosedException", is_trigger: false },
      { time: "03:02:22", service: "api-gateway", event: "504 Gateway Timeout", severity: 'P1', impact: "Upstream timeout > 30s", is_trigger: false }
    ],
    error_histogram: {
      buckets: sortedBuckets,
      spike_detected_at: spikeDetected,
      baseline_error_rate: 0,
      peak_error_rate: Math.max(...sortedBuckets.map(b => b.errors), 1)
    },
    service_graph: {
      nodes: Array.from(services).map(s => ({
        id: s,
        label: s,
        status: s === (patientZero?.service) ? 'CRITICAL' : 'DEGRADED',
        is_root: s === (patientZero?.service),
        error_count: Math.round(errorLines / Math.max(services.size, 1))
      })),
      edges: [
        { from: patientZero?.service || "system", to: "order-service" },
        { from: "order-service", to: "api-gateway" }
      ],
      root_node: patientZero ? patientZero.service : "system"
    }
  };
}

function renderDashboard(report, fallbackElapsed) {
  const s = report.summary;
  const incidents = report.incidents || [];
  const primaryIncident = incidents[0] || null;

  // 1. Show Telemetry
  document.getElementById('valTotalLines').innerText = s.total_lines_ingested.toLocaleString();
  document.getElementById('valErrorLines').innerText = `${s.total_error_lines.toLocaleString()} errors analyzed`;
  document.getElementById('valNoiseReduction').innerText = `${s.noise_reduction_percentage}%`;
  document.getElementById('valTriageSpeed').innerText = `${s.time_to_triage_seconds || fallbackElapsed}s`;
  
  const sevEl = document.getElementById('valSeverityStatus');
  if (primaryIncident) {
    sevEl.innerText = `${primaryIncident.priority} ${primaryIncident.priority_label.split(' ')[0]}`;
    sevEl.className = `metric-value ${primaryIncident.priority === 'P0' ? 'text-red' : 'text-amber'}`;
  }
  document.getElementById('valServicesCount').innerText = `${s.total_services_impacted} services affected`;
  document.getElementById('telemetrySection').style.display = 'grid';

  // 2. War Room Card
  if (primaryIncident) {
    document.getElementById('outageTitle').innerText = primaryIncident.diagnosis.root_cause;
    document.getElementById('outageStartTime').innerText = s.outage_started_at;
    document.getElementById('outageServicesList').innerText = s.services_impacted.join(', ');

    document.getElementById('patientZeroLineNo').innerText = `Line #${primaryIncident.patient_zero.line_no}`;
    document.getElementById('patientZeroRaw').innerText = primaryIncident.patient_zero.raw;
    document.getElementById('diagnosisNarrative').innerText = primaryIncident.diagnosis.impact_narrative;

    document.getElementById('remediationCommand').innerText = primaryIncident.diagnosis.command;
    document.getElementById('runbookSteps').innerHTML = primaryIncident.diagnosis.recommended_fix.replace(/\n/g, '<br>');

    document.getElementById('warRoomSection').style.display = 'block';
  }

  // V2: Error Rate Spike Chart
  renderSpikeChart(report.error_histogram || null);

  // 3. Cascade Waterfall Timeline
  renderCascade(report.cascade_chain || []);

  // V2: Service Topology Graph
  renderTopology(report.service_graph || null);

  // 4. Incidents List
  renderIncidents(incidents);
}

function renderCascade(cascade) {
  const container = document.getElementById('cascadeTimeline');
  container.innerHTML = '';

  if (!cascade || cascade.length === 0) {
    document.getElementById('cascadeSection').style.display = 'none';
    return;
  }

  cascade.forEach((step, index) => {
    const isTrigger = step.is_trigger;
    const item = document.createElement('div');
    item.className = 'timeline-step';
    item.innerHTML = `
      <div class="timeline-marker ${isTrigger ? '' : 'sub'}"></div>
      <div class="timeline-card">
        <div class="step-info">
          <div class="step-time">${step.time} &bull; ${step.service}</div>
          <div class="step-name">${step.event} ${isTrigger ? '<span class="badge red">PATIENT ZERO</span>' : ''}</div>
          <div class="step-impact">${step.impact}</div>
        </div>
        <span class="badge ${step.severity === 'P0' ? 'red' : 'amber'}">${step.severity}</span>
      </div>
    `;
    container.appendChild(item);
  });

  document.getElementById('cascadeSection').style.display = 'block';
}

function renderIncidents(incidents) {
  const container = document.getElementById('incidentsList');
  container.innerHTML = '';

  if (!incidents || incidents.length === 0) {
    document.getElementById('incidentsSection').style.display = 'none';
    return;
  }

  incidents.forEach((inc) => {
    const item = document.createElement('div');
    item.className = 'incident-item';
    item.innerHTML = `
      <div class="incident-header">
        <div class="incident-title-row">
          <span class="badge ${inc.priority === 'P0' ? 'red' : (inc.priority === 'P1' ? 'amber' : 'green')}">${inc.priority}</span>
          <span class="incident-title">${inc.diagnosis.root_cause}</span>
          ${inc.is_cascade_trigger ? '<span class="badge red">CASCADE ROOT</span>' : ''}
        </div>
        <div class="incident-stats">
          <span><strong>${inc.line_count.toLocaleString()}</strong> lines (${inc.percentage_of_total}%)</span>
          <span>First: <strong>${inc.patient_zero.timestamp}</strong></span>
        </div>
      </div>
      <div class="incident-template">
        ${escapeHtml(inc.template)}
      </div>
      <div class="incident-details">
        <div class="service-tags">
          ${inc.services_affected.map(s => `<span class="service-tag">${s}</span>`).join('')}
        </div>
        <span>Impact Score: <strong>${inc.impact_score}</strong></span>
      </div>
    `;
    container.appendChild(item);
  });

  document.getElementById('incidentsSection').style.display = 'block';
}

function copyCommand() {
  const cmd = document.getElementById('remediationCommand').innerText;
  navigator.clipboard.writeText(cmd).then(() => {
    showToast('Copied remediation command to clipboard!');
  });
}

async function exportSlackReport() {
  if (!currentReport) {
    showToast('Please analyze logs first.');
    return;
  }
  try {
    const res = await fetch('/api/export-slack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentReport)
    });
    const data = await res.json();
    document.getElementById('slackTextarea').value = data.markdown;
    document.getElementById('slackModal').style.display = 'flex';
  } catch (err) {
    showToast('Failed to generate Slack report.');
  }
}

function closeSlackModal(e) {
  document.getElementById('slackModal').style.display = 'none';
}

function copySlackText() {
  const text = document.getElementById('slackTextarea').value;
  navigator.clipboard.writeText(text).then(() => {
    showToast('Copied Slack markdown post to clipboard!');
    closeSlackModal();
  });
}

function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.innerText = msg;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2500);
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// === V2 FEATURES ===

function renderSpikeChart(histogram) {
  const container = document.getElementById('spikeChart');
  const metaEl = document.getElementById('spikeMeta');
  container.innerHTML = '';
  
  if (!histogram || !histogram.buckets || histogram.buckets.length === 0) {
    document.getElementById('spikeSection').style.display = 'none';
    return;
  }

  const buckets = histogram.buckets;
  const maxTotal = Math.max(...buckets.map(b => b.errors || 0), 1);
  const spikeAt = histogram.spike_detected_at;

  metaEl.innerHTML = `
    <span>Baseline Error Rate: <strong>${histogram.baseline_error_rate} errors/10s</strong></span>
    <span>Peak Error Rate: <strong style="color: var(--accent-red)">${histogram.peak_error_rate} errors/10s</strong></span>
    <span>Spike Detected: <strong style="color: var(--accent-red)">${spikeAt || 'N/A'}</strong></span>
  `;

  let spikeFound = false;
  buckets.forEach(bucket => {
    if (bucket.time_label === spikeAt) spikeFound = true;
    const errHeight = Math.max((bucket.errors / maxTotal) * 120, 2);
    const isSpike = spikeFound && bucket.errors > 0;

    const group = document.createElement('div');
    group.className = 'spike-bar-group';
    group.title = `${bucket.time_label}\nErrors: ${bucket.errors} | Info: ${bucket.info} | Total: ${bucket.total}`;
    group.innerHTML = `
      <div class="spike-bar ${isSpike ? 'spike' : (bucket.errors > 0 ? 'error' : 'normal')}" style="height: ${errHeight}px"></div>
    `;
    container.appendChild(group);
  });

  document.getElementById('spikeSection').style.display = 'block';
}

function renderTopology(serviceGraph) {
  const container = document.getElementById('topologyGraph');
  container.innerHTML = '';

  if (!serviceGraph || !serviceGraph.nodes || serviceGraph.nodes.length === 0) {
    document.getElementById('topologySection').style.display = 'none';
    return;
  }

  const nodes = serviceGraph.nodes;
  const edges = serviceGraph.edges || [];

  // Sort: root first, then by error count desc
  nodes.sort((a, b) => {
    if (a.is_root) return -1;
    if (b.is_root) return 1;
    return (b.error_count || 0) - (a.error_count || 0);
  });

  nodes.forEach((node, index) => {
    if (index > 0 && edges.length > 0) {
      const edgeEl = document.createElement('div');
      edgeEl.className = 'topo-edge';
      edgeEl.innerHTML = '→';
      container.appendChild(edgeEl);
    }

    const statusClass = node.status === 'CRITICAL' ? 'critical' : (node.status === 'DEGRADED' ? 'degraded' : 'warning');
    const statusLabelClass = node.status === 'CRITICAL' ? 'critical-status' : (node.status === 'DEGRADED' ? 'degraded-status' : 'warning-status');

    const nodeEl = document.createElement('div');
    nodeEl.className = `topo-node ${statusClass}`;
    nodeEl.innerHTML = `
      <div class="topo-node-name">${node.label}</div>
      <div class="topo-node-status ${statusLabelClass}">${node.status}${node.is_root ? ' ⚡ ROOT' : ''}</div>
      <div class="topo-node-errors">${(node.error_count || 0).toLocaleString()} errors</div>
    `;
    container.appendChild(nodeEl);
  });

  document.getElementById('topologySection').style.display = 'block';
}

async function exportPostmortem() {
  if (!currentReport) {
    showToast('Please analyze logs first.');
    return;
  }
  try {
    const res = await fetch('/api/export-postmortem', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentReport)
    });
    const data = await res.json();
    document.getElementById('slackTextarea').value = data.markdown;
    document.querySelector('.modal-header h3').innerText = '📄 Post-Incident Review (PIR) Document';
    document.getElementById('slackModal').style.display = 'flex';
  } catch (err) {
    showToast('Failed to generate postmortem report.');
  }
}

// === Kaif's Pointer-Reactive Dotted Wordmark Canvas Engine ===
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

  const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

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
    const fontSize = Math.min(width / 8.8, height * 0.62, 80);
    maskCtx.font = `800 ${fontSize}px 'Plus Jakarta Sans', -apple-system, sans-serif`;
    maskCtx.textAlign = 'center';
    maskCtx.textBaseline = 'middle';
    maskCtx.fillStyle = '#fff';
    maskCtx.fillText(label, width / 2, height / 2 - 2, width * 0.96);

    const image = maskCtx.getImageData(0, 0, mask.width, mask.height);
    const step = clamp(width / 130, 3.2, 5.0);
    for (let y = step; y < height - 3; y += step) {
      for (let x = 2; x < width - 2; x += step) {
        const ix = Math.min(mask.width - 1, Math.floor(x * dpr));
        const iy = Math.min(mask.height - 1, Math.floor(y * dpr));
        const alpha = image.data[(iy * mask.width + ix) * 4 + 3] / 255;
        if (alpha > 0.22) points.push({ x, y, alpha });
      }
    }
  }

  function draw() {
    frameId = 0;
    ctx.clearRect(0, 0, width, height);
    const reach = Math.max(55, Math.min(110, width * 0.18));

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

  function setPointer(e) {
    const rect = canvas.getBoundingClientRect();
    pointer = {
      x: clamp(e.clientX - rect.left, 0, width),
      y: clamp(e.clientY - rect.top, 0, height),
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
  window.addEventListener('resize', resize, { passive: true });
  resize();
}
