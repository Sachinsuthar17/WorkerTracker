// ---- CONFIG ----
// For demo only: must match DEVICE_SECRET in your server env (or change it).
const DEVICE_SECRET = "my-esp32-secret";

// ---- Helpers ----
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}
function el(id) { return document.getElementById(id); }
function rowHTML(cells) {
  return `<tr>${cells.map(c => `<td class="pr-4">${c}</td>`).join("")}</tr>`;
}

// ---- Stats + Activity + Chart ----
async function loadStats() {
  const s = await getJSON("/api/stats");
  el("statActive").textContent  = s.active_workers ?? "0";
  el("statOps").textContent     = s.total_operations ?? "0";
  el("statBundles").textContent = s.total_bundles ?? "0";
  el("statEarnings").textContent = (s.earnings ?? 0).toLocaleString(undefined, {style:"currency", currency:"USD"});
}

async function loadActivities() {
  const items = await getJSON("/api/activities");
  const ul = el("activityList");
  ul.innerHTML = items.map(a => `
    <li class="py-2">
      <div class="flex justify-between">
        <div>
          <div class="font-medium">${a.actor}</div>
          <div class="text-slate-500 text-xs">${a.department || "—"}</div>
        </div>
        <div class="text-slate-600 text-sm">${a.action}</div>
      </div>
      <div class="text-slate-400 text-xs mt-1">${a.time}</div>
    </li>
  `).join("");
}

async function loadChart() {
  const data = await getJSON("/api/chart-data");
  const ctx = el("chartMonthly").getContext("2d");
  new Chart(ctx, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [{
        label: "Work scans",
        data: data.values,
        tension: 0.35,
        fill: false
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true }
      }
    }
  });
}

// ---- Workers ----
async function loadWorkers() {
  const q = el("workerSearch").value.trim();
  const d = el("workerDept").value;
  const url = new URL(location.origin + "/api/workers");
  if (q) url.searchParams.set("q", q);
  if (d) url.searchParams.set("department", d);
  const workers = await getJSON(url.toString());
  el("workersBody").innerHTML = workers.map(w => rowHTML([
    w.name, w.token_id, w.department, w.line, w.status
  ])).join("");
}

// ---- Bundles ----
async function loadBundles() {
  const list = await getJSON("/api/bundles");
  el("bundlesBody").innerHTML = list.map(b => rowHTML([
    `<span class="font-medium">${b.id}</span>`,
    b.qty,
    `<span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs border
      ${b.status === "Completed" ? "bg-green-50 border-green-200 text-green-700" :
        b.status === "In Progress" ? "bg-amber-50 border-amber-200 text-amber-700" :
        b.status === "QA" ? "bg-blue-50 border-blue-200 text-blue-700" :
        "bg-slate-50 border-slate-200 text-slate-700"}">${b.status}</span>`
  ])).join("");
}

// ---- Uploads (OB/PDF) ----
// These endpoints are stubs server-side; this just demonstrates posting FormData.
async function postForm(url, file) {
  const fd = new FormData();
  if (file) fd.append("file", file);
  const r = await fetch(url, { method: "POST", body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.message || `Upload failed: ${r.status}`);
  return j;
}

function wireUploads() {
  el("formOB").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = el("obFile").files[0];
    el("obMsg").textContent = "Uploading…";
    try {
      const res = await postForm("/api/upload/ob", file);
      el("obMsg").textContent = res.message || "Uploaded.";
    } catch (err) {
      el("obMsg").textContent = err.message;
    }
  });

  el("formPO").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = el("poFile").files[0];
    el("poMsg").textContent = "Uploading…";
    try {
      const res = await postForm("/api/upload/po", file);
      el("poMsg").textContent = res.message || "Uploaded.";
    } catch (err) {
      el("poMsg").textContent = err.message;
    }
  });
}

// ---- Scan demo ----
async function simulateScan() {
  const token = el("scanToken").value.trim();
  const scanType = el("scanType").value;
  const log = el("scanLog");
  if (!token) { log.textContent = "Enter a token id (e.g. 1001)."; return; }

  log.textContent = "Sending…";
  try {
    const r = await fetch("/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token_id: token,
        secret: DEVICE_SECRET,     // must match server env DEVICE_SECRET
        scan_type: scanType
      })
    });
    const j = await r.json();
    log.textContent = JSON.stringify(j, null, 2);
    await Promise.all([loadStats(), loadActivities()]);
  } catch (e) {
    log.textContent = e.message;
  }
}

// ---- Boot ----
document.addEventListener("DOMContentLoaded", () => {
  // initial loads
  loadStats();
  loadActivities();
  loadChart();
  loadWorkers();
  loadBundles();
  // wiring
  el("workerReload").addEventListener("click", loadWorkers);
  el("workerSearch").addEventListener("input", () => {
    // debounce-lite
    clearTimeout(window.__wdeb);
    window.__wdeb = setTimeout(loadWorkers, 250);
  });
  el("workerDept").addEventListener("change", loadWorkers);
  wireUploads();
  el("scanBtn").addEventListener("click", simulateScan);
});
