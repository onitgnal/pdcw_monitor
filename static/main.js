const WS_URL = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';

const statusEl = document.getElementById('status');
const channelListEl = document.getElementById('channel-list');
const liveValuesEl = document.getElementById('live-values');
const selectAllBtn = document.getElementById('select-all');
const selectNoneBtn = document.getElementById('select-none');
const clearBtn = document.getElementById('clear-btn');
const winMinsInput = document.getElementById('win-mins');

let socket;
let channels = [];
let selected = new Set();
let traces = new Set();     // names currently added to Plotly
let lastValues = {};
let lastTs = null;
let avgDtMs = 100;          // EMA of sample period; defaults ~10 Hz

const chartDiv = document.getElementById('chart');
const layout = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  margin: {l:50,r:20,t:30,b:30},
  xaxis: { title: 'Time', type: 'date', showgrid: true, gridcolor: '#1f2937' },
  yaxis: { title: 'Value', showgrid: true, gridcolor: '#1f2937' },
  legend: { orientation: 'h' }
};
Plotly.newPlot(chartDiv, [], layout, {responsive:true, displaylogo:false});

function addTraceIfNeeded(name) {
  if (traces.has(name)) return;
  traces.add(name);
  Plotly.addTraces(chartDiv, [{
    x: [], y: [], mode: 'lines', name: name, line: { width: 2 }
  }]);
}

function removeTrace(name) {
  const idx = chartDiv.data.findIndex(t => t.name === name);
  if (idx >= 0) Plotly.deleteTraces(chartDiv, idx);
  traces.delete(name);
}

function windowPoints() {
  const mins = Math.max(0.5, parseFloat(winMinsInput.value || '5'));
  const winMs = mins * 60 * 1000;
  const dt = Math.max(10, avgDtMs); // min 10ms guard
  return Math.max(10, Math.ceil(winMs / dt));
}

function renderLiveValues() {
  liveValuesEl.innerHTML = '';
  for (const name of channels) {
    const label = document.createElement('div'); label.className = 'val-name'; label.textContent = name;
    const val = document.createElement('div'); val.className = 'val-number';
    const v = lastValues[name];
    val.textContent = (v === undefined) ? '—' : formatValue(name, v);
    liveValuesEl.appendChild(label); liveValuesEl.appendChild(val);
  }
}

function formatValue(name, v) {
  if (/_T$/.test(name)) return `${v.toFixed(2)} °C`;
  if (/_H$/.test(name)) return `${v.toFixed(2)} %RH`;
  if (/_P$/.test(name)) return `${v.toFixed(2)} hPa`;
  if (/_V$/.test(name)) return `${v.toFixed(4)} V`;
  if (/IuA$/.test(name)) return `${v.toFixed(2)} µA`;
  return Number(v).toPrecision(5);
}

function buildChannelList() {
  channelListEl.innerHTML = '';
  for (const name of channels) {
    const label = document.createElement('div'); label.className = 'channel-name'; label.textContent = name;
    const check = document.createElement('input'); check.type = 'checkbox'; check.className = 'channel-check';
    check.checked = selected.has(name);
    check.addEventListener('change', () => {
      if (check.checked) { selected.add(name); addTraceIfNeeded(name); }
      else { selected.delete(name); removeTrace(name); }
    });
    channelListEl.appendChild(label); channelListEl.appendChild(check);
  }
}

selectAllBtn.addEventListener('click', () => {
  channels.forEach(n => { if (!selected.has(n)) { selected.add(n); addTraceIfNeeded(n); } });
  buildChannelList();
});
selectNoneBtn.addEventListener('click', () => {
  [...selected].forEach(n => removeTrace(n));
  selected.clear();
  buildChannelList();
});

// FIX: clear by deleting all traces and resetting our set.
// Next incoming data tick will re-add traces for checked channels.
clearBtn.addEventListener('click', () => {
  const n = chartDiv.data.length;
  if (n > 0) {
    const inds = Array.from({ length: n }, (_, i) => i);
    Plotly.deleteTraces(chartDiv, inds);
  }
  traces.clear();
});

function connect() {
  socket = new WebSocket(WS_URL);
  let pingTimer;

  socket.onopen = () => {
    statusEl.textContent = 'connected';
    pingTimer = setInterval(() => { try { socket.send('ping'); } catch {} }, 10000);
  };
  socket.onclose = () => {
    statusEl.textContent = 'reconnecting…';
    clearInterval(pingTimer);
    setTimeout(connect, 1000);
  };
  socket.onerror = () => { /* no-op */ };

  socket.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }

    if (msg.meta && msg.meta.channels) {
      channels = msg.meta.channels;
      buildChannelList();
      renderLiveValues();
      return;
    }

    const now = msg.ts ? Number(msg.ts) : Date.now();
    if (lastTs != null) {
      const dt = Math.max(1, now - lastTs);
      avgDtMs = 0.9 * avgDtMs + 0.1 * dt;
    }
    lastTs = now;

    // show live Hz in status
    const hz = 1000 / Math.max(1, avgDtMs);
    statusEl.textContent = `connected · ${hz.toFixed(1)} Hz`;

    if (msg.error) { return; }

    const vals = msg.values || {};
    lastValues = vals;
    renderLiveValues();

    // incremental update for selected traces (rolling window via maxPoints)
    const xUpdates = [];
    const yUpdates = [];
    const inds = [];
    const nameToIdx = {};
    chartDiv.data.forEach((t, i) => { nameToIdx[t.name] = i; });

    for (const name of selected) {
      if (!(name in vals)) continue;
      addTraceIfNeeded(name);
      const idx = (nameToIdx[name] ?? chartDiv.data.findIndex(t => t.name === name));
      if (idx < 0) continue;
      inds.push(idx);
      xUpdates.push([now]);
      yUpdates.push([vals[name]]);
    }

    if (inds.length) {
      Plotly.extendTraces(chartDiv, { x: xUpdates, y: yUpdates }, inds, windowPoints());
    }
  };
}

connect();
