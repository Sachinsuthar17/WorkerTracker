// Minimal dashboard polling (keeps your existing UI logic)
async function fetchStats() {
  try {
    const r = await fetch('/api/stats');
    const data = await r.json();
    // Update UI widgets here...
    // Example:
    // document.querySelector('#piecesToday').textContent = data.pieces_today;
    // document.querySelector('#workersToday').textContent = data.workers_today;
    // document.querySelector('#earningsToday').textContent = data.earnings_today.toFixed(2);
    // document.querySelector('#activeWorker').textContent = data.active_worker || '—';
    console.debug('[stats]', data);
  } catch (e) {
    console.error('stats error', e);
  }
}

async function fetchActivities(limit = 100) {
  try {
    const r = await fetch('/api/activities?limit=' + encodeURIComponent(limit));
    const data = await r.json();
    // Render activity table/list...
    console.debug('[activities]', data);
  } catch (e) {
    console.error('activities error', e);
  }
}

// Call on load and every few seconds
fetchStats();
fetchActivities();
setInterval(fetchStats, 5_000);
setInterval(fetchActivities, 15_000);

// -----------------------------------------------------------------------------
// TEST HELPER for unified /scan (useful when validating QR content & server)
// -----------------------------------------------------------------------------
window.testScan = async function(tokenNoPrefix, barcodeRawOrNull) {
  // The ESP32 sends:
  // { secret, token_id: "W:<token>", [barcode: "B:<code>"] }
  const payload = {
    secret: "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F",
    token_id: tokenNoPrefix ? ("W:" + tokenNoPrefix) : undefined,
    barcode: barcodeRawOrNull ? ("B:" + barcodeRawOrNull) : undefined,
  };

  // Remove undefined keys
  Object.keys(payload).forEach(k => payload[k] === undefined && delete payload[k]);

  console.log('POST /scan', payload);
  const r = await fetch('/scan', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  console.log('RESP /scan', data);

  // You can reflect this to UI if you want:
  // e.g., show toast, update active worker badge from data.active_worker, etc.
  // data.status will be "logged_in", "logged_out", or "saved".
  return data;
};
