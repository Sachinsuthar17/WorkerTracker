/* Live dashboard wiring for /api/stats and /api/activities */

let prodChart, workerChart;

async function fetchJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}

function renderStats(s) {
  s = s || {};
  const byHour = Array.isArray(s.byHour) ? s.byHour : [];
  const topWorkers = Array.isArray(s.topWorkers) ? s.topWorkers : [];

  const el = document.getElementById('statsGrid');
  if (el) {
    el.innerHTML = `
      <div class="stat"><h4>Total Pieces (Today)</h4><div class="v">${s.totalPiecesToday ?? 0}</div></div>
      <div class="stat"><h4>Total Earnings (Today)</h4><div class="v">₹ ${Math.round(s.totalEarningsToday ?? 0)}</div></div>
      <div class="stat"><h4>Active Workers</h4><div class="v">${s.activeWorkers ?? 0}</div></div>
      <div class="stat"><h4>Average Rate</h4><div class="v">₹ ${Math.round(s.averageRate ?? 0)}</div></div>
    `;
  }

  // Hourly chart
  const hours = byHour.map(x => x.hour);
  const pcs = byHour.map(x => x.pieces);
  const prodCtx = document.getElementById('productionChart');
  if (prodCtx) {
    if (!prodChart) {
      prodChart = new Chart(prodCtx.getContext('2d'), {
        type: 'line',
        data: { labels: hours, datasets: [{ label: 'Pieces', data: pcs, tension: .3 }] },
        options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true } } }
      });
    } else {
      prodChart.data.labels = hours;
      prodChart.data.datasets[0].data = pcs;
      prodChart.update();
    }
  }

  // Top workers chart
  const names = topWorkers.map(x => x.name);
  const values = topWorkers.map(x => x.pieces);
  const workerCtx = document.getElementById('workerChart');
  if (workerCtx) {
    if (!workerChart) {
      workerChart = new Chart(workerCtx.getContext('2d'), {
        type: 'bar',
        data: { labels: names, datasets: [{ label: 'Pieces', data: values }] },
        options: { indexAxis: 'y', responsive: true, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } } }
      });
    } else {
      workerChart.data.labels = names;
      workerChart.data.datasets[0].data = values;
      workerChart.update();
    }
  }
}

function renderActivities(list) {
  list = Array.isArray(list) ? list : [];
  const el = document.getElementById('activitiesList');
  if (el) {
    el.innerHTML = list.map(a => `
      <div class="activity">
        <div class="muted">${new Date(a.time).toLocaleTimeString()}</div>
        <div><strong>${a.worker}</strong> <span class="muted">(${a.line || '—'})</span></div>
        <div class="muted">Order: ${a.order || '—'}</div>
        <div class="muted">Op: ${a.operation || '—'}</div>
        <div>+${a.pieces} • ₹ ${Math.round(a.earnings || 0)}</div>
      </div>
    `).join('');
  }
  const lu = document.getElementById('lastUpdated');
  if (lu) lu.textContent = 'Updated ' + new Date().toLocaleTimeString();
}

async function refresh() {
  try {
    const [stats, acts] = await Promise.all([
      fetchJSON('/api/stats'),
      fetchJSON('/api/activities')
    ]);
    renderStats(stats);
    renderActivities(acts);
  } catch (e) {
    console.error('Refresh failed', e);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  refresh();
  setInterval(refresh, (window.DASHBOARD_POLL_MS || 2000));
});
