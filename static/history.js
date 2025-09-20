document.addEventListener('DOMContentLoaded', () => {
  const startTimeEl = document.getElementById('start-time');
  const endTimeEl = document.getElementById('end-time');
  const limitEl = document.getElementById('limit');
  const plotBtn = document.getElementById('plot-btn');
  const channelListEl = document.getElementById('channel-list');
  const selectAllBtn = document.getElementById('select-all');
  const selectNoneBtn = document.getElementById('select-none');
  const chartDiv = document.getElementById('chart');
  const saveCsvBtn = document.getElementById('save-csv-btn');
  const savePlotBtn = document.getElementById('save-plot-btn');

  let allChannels = [];
  let plottedData = null;

  const chartLayout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: { l: 50, r: 20, t: 30, b: 30 },
    xaxis: { title: 'Time', type: 'date', showgrid: true, gridcolor: '#1f2937' },
    yaxis: { title: 'Value', showgrid: true, gridcolor: '#1f2937' },
    legend: { orientation: 'h' }
  };
  Plotly.newPlot(chartDiv, [], chartLayout, { responsive: true, displaylogo: false });

  function renderChannelList() {
    channelListEl.innerHTML = '';
    const selected = new Set(getCheckedChannels());
    for (const name of allChannels) {
      const label = document.createElement('div');
      label.className = 'channel-name';
      label.textContent = name;
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.className = 'channel-check';
      check.value = name;
      check.checked = selected.has(name);
      channelListEl.appendChild(label);
      channelListEl.appendChild(check);
    }
  }

  function getCheckedChannels() {
    return [...channelListEl.querySelectorAll('input:checked')].map(el => el.value);
  }

  async function fetchChannels() {
    try {
      // This endpoint will be created in a later step
      const response = await fetch('/api/channels');
      if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
      allChannels = await response.json();
      renderChannelList();
    } catch (error) {
      console.error('Failed to fetch channels:', error);
      channelListEl.textContent = 'Error loading channels.';
    }
  }

  plotBtn.addEventListener('click', async () => {
    const start = startTimeEl.value;
    const end = endTimeEl.value;
    const limit = limitEl.value;
    const channels = getCheckedChannels();

    if (!start || !end) {
      alert('Please select a start and end time.');
      return;
    }
    if (channels.length === 0) {
      alert('Please select at least one channel.');
      return;
    }

    const params = new URLSearchParams({
      start: new Date(start).toISOString(),
      end: new Date(end).toISOString(),
      limit: limit,
      channels: channels.join(','),
    });

    try {
      const response = await fetch(`/api/history?${params}`);
      if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
      const data = await response.json();
      plottedData = data; // Save for export

      const traces = data.columns.slice(1).map((name, i) => ({
        x: data.rows.map(r => new Date(r[0])),
        y: data.rows.map(r => r[i + 1]),
        mode: 'lines',
        name: name,
      }));

      Plotly.newPlot(chartDiv, traces, chartLayout);
    } catch (error) {
      console.error('Failed to plot data:', error);
      alert('Could not load data. Check console for details.');
    }
  });

  selectAllBtn.addEventListener('click', () => {
    channelListEl.querySelectorAll('input').forEach(el => el.checked = true);
  });

  selectNoneBtn.addEventListener('click', () => {
    channelListEl.querySelectorAll('input').forEach(el => el.checked = false);
  });

  saveCsvBtn.addEventListener('click', () => {
    if (!plottedData) {
      alert('No data to save. Please plot something first.');
      return;
    }
    const { columns, rows } = plottedData;
    let csvContent = "data:text/csv;charset=utf-8,"
      + columns.join(",") + "\\n"
      + rows.map(e => e.join(",")).join("\\n");

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "history_export.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  });

  savePlotBtn.addEventListener('click', () => {
    Plotly.downloadImage(chartDiv, {format: 'png', width: 1200, height: 600, filename: 'history_plot'});
  });

  // Set default times (e.g., last 24 hours)
  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  endTimeEl.value = now.toISOString().slice(0, 16);
  startTimeEl.value = yesterday.toISOString().slice(0, 16);

  // Initial fetch of channels
  fetchChannels();
});
