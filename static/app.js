// Triage3AM Frontend Controller
let currentReport = null;

document.addEventListener('DOMContentLoaded', () => {
  initClock();
  setupTextareaListener();
  setupDragAndDrop();
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
  currentReport = null;
  showToast('Cleared input');
}

async function loadPreset(presetName) {
  showToast(`Loading 10,000 lines (${presetName})...`);
  try {
    const res = await fetch(`/api/load-preset?name=${encodeURIComponent(presetName)}`);
    const data = await res.json();
    if (data.content) {
      document.getElementById('logInput').value = data.content;
      updateLineCount();
      showToast(`Loaded 10,000 lines! Analyzing...`);
      await analyzeLogs();
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
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ logs: rawText })
    });
    const report = await res.json();
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

  // 3. Cascade Waterfall Timeline
  renderCascade(report.cascade_chain || []);

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
