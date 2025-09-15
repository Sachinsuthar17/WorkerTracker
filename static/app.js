/* Sidebar switching */
const navItems = document.querySelectorAll(".nav-item");
const sections = document.querySelectorAll(".section");
navItems.forEach(item => {
  item.addEventListener("click", e => {
    e.preventDefault();
    navItems.forEach(i => i.classList.remove("active"));
    sections.forEach(s => s.classList.remove("active"));
    item.classList.add("active");
    const id = item.dataset.section;
    document.getElementById(id).classList.add("active");
  });
});

/* Refresh button -> reload KPIs + charts + activity */
const refreshBtn = document.getElementById("refreshBtn");
refreshBtn?.addEventListener("click", () => loadDashboard());

/* Dashboard loaders */
async function loadDashboard() {
  try {
    const [stats, charts, acts] = await Promise.all([
      fetch("/api/stats").then(r => r.json()),
      fetch("/api/chart-data").then(r => r.json()),
      fetch("/api/activities").then(r => r.json()),
    ]);

    document.getElementById("activeWorkers").textContent = stats.active_workers ?? 0;
    document.getElementById("totalBundles").textContent = stats.total_bundles ?? 0;
    document.getElementById("totalOperations").textContent = stats.total_operations ?? 0;
    document.getElementById("totalEarnings").textContent = `₹${stats.total_earnings ?? 0}`;
    document.getElementById("lastUpdated").textContent = `Last updated: ${new Date(stats.last_updated).toLocaleString()}`;

    drawBundleStatus(charts.bundleStatus.labels, charts.bundleStatus.values);
    drawDepartment(charts.departmentWorkload.labels, charts.departmentWorkload.values);

    const feed = document.getElementById("activityFeed");
    feed.innerHTML = acts.map(a => `
      <div class="item">
        <div>${a.message}</div>
        <div class="time">${new Date(a.created_at).toLocaleTimeString()}</div>
      </div>
    `).join("");
  } catch (e) {
    console.error(e);
  }
}

/* Charts */
let bundleChart, deptChart;
function drawBundleStatus(labels, values) {
  const ctx = document.getElementById("bundleStatusChart");
  if (bundleChart) bundleChart.destroy();
  bundleChart = new Chart(ctx, {
    type: "doughnut",
    data: { labels, datasets: [{ data: values }] },
    options: { responsive: true, plugins: { legend: { position: "bottom" } } }
  });
}
function drawDepartment(labels, values) {
  const ctx = document.getElementById("departmentChart");
  if (deptChart) deptChart.destroy();
  deptChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: values }] },
    options: { responsive: true, plugins: { legend: { display:false } },
      scales: { y: { beginAtZero: true } } }
  });
}

/* Workers table */
async function loadWorkers() {
  const params = new URLSearchParams();
  const q = document.getElementById("workerSearch").value.trim();
  const dept = document.getElementById("departmentFilter").value;
  const status = document.getElementById("statusFilter").value;
  if (q) params.set("q", q);
  if (dept) params.set("department", dept);
  if (status) params.set("status", status);

  const rows = await fetch(`/api/workers?${params}`).then(r => r.json());
  const tb = document.getElementById("workersTable");
  tb.innerHTML = rows.map(r => `
    <tr>
      <td>${r.name}</td>
      <td>${r.token_id}</td>
      <td>${r.department ?? "-"}</td>
      <td>${r.line ?? "-"}</td>
      <td>${r.status}</td>
      <td><code>${r.qrcode}</code></td>
      <td><button class="btn btn--outline btn-sm" onclick="alert('Coming soon')">Edit</button></td>
    </tr>
  `).join("");

  // Fill department dropdown once
  const set = new Set(rows.map(r => r.department).filter(Boolean));
  const deptSel = document.getElementById("departmentFilter");
  if (deptSel.options.length <= 1) {
    [...set].sort().forEach(d => {
      const opt = document.createElement("option");
      opt.value = d; opt.textContent = d;
      deptSel.appendChild(opt);
    });
  }
}
document.getElementById("workerSearch")?.addEventListener("input", () => loadWorkers());
document.getElementById("departmentFilter")?.addEventListener("change", () => loadWorkers());
document.getElementById("statusFilter")?.addEventListener("change", () => loadWorkers());

/* Operations table */
async function loadOperations() {
  const q = document.getElementById("operationSearch").value.trim().toLowerCase();
  const rows = await fetch("/api/operations").then(r => r.json());
  const filtered = q
    ? rows.filter(r =>
        `${r.seq_no} ${r.op_no} ${r.description} ${r.machine} ${r.department}`
          .toLowerCase().includes(q))
    : rows;
  const tb = document.getElementById("operationsTable");
  tb.innerHTML = filtered.map(r => `
    <tr>
      <td>${r.seq_no}</td>
      <td>${r.op_no}</td>
      <td>${r.description}</td>
      <td>${r.machine ?? "-"}</td>
      <td>${r.department ?? "-"}</td>
      <td>${r.std_min}</td>
      <td>${r.piece_rate}</td>
    </tr>
  `).join("");
}
document.getElementById("operationSearch")?.addEventListener("input", () => loadOperations());

/* Bundles grid */
async function loadBundles() {
  const rows = await fetch("/api/bundles").then(r => r.json());
  const grid = document.getElementById("bundlesGrid");
  grid.innerHTML = rows.map(r => `
    <div class="bundle">
      <div class="code">${r.bundle_code}</div>
      <div class="meta">Qty: ${r.qty}</div>
      <div class="meta">Status: ${r.status}</div>
      <div class="meta">Barcode: ${r.barcode_value ?? "-"}</div>
      <button class="btn btn--primary" onclick="simulateScan('${r.bundle_code}')">Scan</button>
    </div>
  `).join("");
}
async function simulateScan(code) {
  const fake = `${code}-${Math.floor(1000 + Math.random()*8999)}`;
  const res = await fetch("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ barcode: fake })
  }).then(r => r.json());
  if (res.ok) {
    document.getElementById("scanStatus").textContent = `Scanned ${fake} → ${res.status}`;
    await Promise.all([loadDashboard(), loadBundles()]);
  } else {
    alert(res.error || "Scan failed");
  }
}

/* Scanner buttons */
const startBtn = document.getElementById("startScan");
const stopBtn = document.getElementById("stopScan");
const resetBtn = document.getElementById("resetScan");

let scanning = false, intervalId = null;
startBtn?.addEventListener("click", () => {
  if (scanning) return;
  scanning = true;
  startBtn.disabled = true;
  stopBtn.disabled = false;
  document.getElementById("scanStatus").textContent = "Scanning...";
  intervalId = setInterval(async () => {
    const bundles = await fetch("/api/bundles").then(r => r.json());
    if (bundles.length === 0) return;
    const pick = bundles[Math.floor(Math.random()*bundles.length)];
    await simulateScan(pick.bundle_code);
  }, 3000);
});
stopBtn?.addEventListener("click", () => {
  scanning = false;
  startBtn.disabled = false;
  stopBtn.disabled = true;
  clearInterval(intervalId);
  document.getElementById("scanStatus").textContent = "Stopped";
});
resetBtn?.addEventListener("click", () => {
  scanning = false;
  clearInterval(intervalId);
  startBtn.disabled = false;
  stopBtn.disabled = true;
  document.getElementById("scanStatus").textContent = "Ready to Scan";
});

/* Initial loads */
loadDashboard();
loadWorkers();
loadOperations();
loadBundles();
