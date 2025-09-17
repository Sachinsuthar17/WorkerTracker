/* PMS Frontend (robust, no Jinja in static) */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const on = (el, ev, fn) => el && el.addEventListener(ev, fn);

  let autoRefreshTimer = null;
  let charts = { bundle: null, department: null };

  document.addEventListener("DOMContentLoaded", () => {
    // Sidebar toggle on all pages
    const sidebar = $("#sidebar");
    const sidebarToggle = $("#sidebarToggle");
    on(sidebarToggle, "click", () => sidebar?.classList.toggle("active"));

    // SPA only on index.html (body has data-spa="true" and there are .section nodes)
    const isSPA = document.body.dataset.spa === "true";
    const hasSections = $$(".section").length > 0;

    if (isSPA && hasSections) {
      // In-page nav switching: only preventDefault when we are already on index (path "/")
      $$(".nav-item").forEach(item => {
        on(item, "click", (e) => {
          // If link is to "/" (index) and has a hash, we can SPA-toggle
          const href = item.getAttribute("href") || "";
          const url = new URL(href, location.origin);
          const pointsToIndex = url.pathname === "/";     // do NOT use Jinja here
          const target = item.dataset.section;

          if (pointsToIndex && target) {
            e.preventDefault();
            if (location.hash !== `#${target}`) {
              location.hash = target; // triggers hashchange below
            } else {
              activateSection(target);
              loadSectionData(target);
            }
            if (window.innerWidth <= 768) sidebar?.classList.remove("active");
          }
        });
      });

      // initial state
      activateSectionFromHash();
      loadSectionData(currentSectionId());

      // hash routing
      window.addEventListener("hashchange", () => {
        activateSectionFromHash();
        loadSectionData(currentSectionId());
      });

      // initial data loads (index only)
      loadDashboard();
      loadWorkers();
      loadOperations();
      loadBundles();
      loadProductionOrder();
    } else {
      // Non-SPA pages (add/edit). No in-page toggling; sidebar links navigate to index sections.
    }

    // Wire page controls (guards inside functions make them safe on any page)
    wireDashboardControls();
    wireWorkerControls();
    wireOperationControls();
    wireScanDemo();
  });

  // ---------- SPA helpers ----------
  function currentSectionId() { return (location.hash || "#dashboard").replace("#", ""); }
  function activateSectionFromHash() { activateSection(currentSectionId()); }
  function activateSection(id) {
    const sections = $$(".section");
    if (!sections.length) return;
    sections.forEach(sec => sec.classList.toggle("active", sec.id === id));
    $$(".nav-item").forEach(i => i.classList.remove("active"));
    const activeNav = $(`.nav-item[data-section="${id}"]`);
    activeNav?.classList.add("active");
    manageAutoRefresh(id);
  }
  function manageAutoRefresh(id) {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
    if (id === "dashboard") {
      autoRefreshTimer = setInterval(() => {
        loadDashboardStats();
        loadRecentActivity();
        updateLastUpdated();
      }, 30000);
    }
  }
  function loadSectionData(id) {
    switch (id) {
      case "dashboard": loadDashboard(); break;
      case "workers": loadWorkers(); break;
      case "operations": loadOperations(); break;
      case "bundles": loadBundles(); break;
      case "production-order": loadProductionOrder(); break;
    }
  }

  // ---------- Dashboard ----------
  function wireDashboardControls() {
    const btn = $("#refreshBtn");
    on(btn, "click", async () => {
      const original = btn.textContent;
      btn.disabled = true; btn.textContent = "Refreshing...";
      await loadDashboard();
      btn.disabled = false; btn.textContent = original || "Refresh";
      updateLastUpdated();
    });
  }

  async function loadDashboard() {
    await Promise.all([loadDashboardStats(), loadChartData(), loadRecentActivity()]);
    updateLastUpdated();
  }

  async function loadDashboardStats() {
    try {
      const res = await fetch("/api/dashboard-stats");
      const data = await res.json();
      setText("#activeWorkers", data.activeWorkers ?? 0);
      setText("#totalBundles", data.totalBundles ?? 0);
      setText("#totalOperations", data.totalOperations ?? 0);
      setText("#totalEarnings", typeof data.totalEarnings === "number" ? `₹${data.totalEarnings.toFixed(2)}` : "₹0.00");
      pulseKPI(["#activeWorkers", "#totalBundles", "#totalOperations", "#totalEarnings"]);
    } catch (e) {
      console.error("dashboard-stats error", e);
      setText("#activeWorkers", "0"); setText("#totalBundles", "0");
      setText("#totalOperations", "0"); setText("#totalEarnings", "₹0.00");
    }
  }

  async function loadChartData() {
    try {
      const res = await fetch("/api/chart-data");
      const data = await res.json();
      updateBundleChart(data.bundleStatus || {});
      updateDepartmentChart(data.departmentWorkload || {});
    } catch (e) {
      console.error("chart-data error", e);
      updateBundleChart({ Pending: 3, "In Progress": 5, Completed: 6 });
      updateDepartmentChart({ Cutting: 8, Sewing: 12, Finishing: 6, Quality: 4, Packing: 3 });
    }
  }

  function updateBundleChart(map) {
    const canvas = $("#bundleStatusChart") || $("#bundleChart");
    if (!canvas || !window.Chart) return;
    if (charts.bundle) charts.bundle.destroy();
    charts.bundle = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: Object.keys(map),
        datasets: [{ data: Object.values(map), backgroundColor: ["#f59e0b", "#3b82f6", "#10b981", "#ef4444"], borderWidth: 0 }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }
    });
  }

  function updateDepartmentChart(map) {
    const canvas = $("#departmentChart");
    if (!canvas || !window.Chart) return;
    if (charts.department) charts.department.destroy();
    charts.department = new Chart(canvas, {
      type: "bar",
      data: {
        labels: Object.keys(map),
        datasets: [{ label: "Workers", data: Object.values(map), backgroundColor: "rgba(59,130,246,0.8)", borderColor: "#3b82f6", borderWidth: 1, borderRadius: 8 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: "rgba(255,255,255,0.1)" }, ticks: { color: "#b8bcc8" } },
          y: { beginAtZero: true, grid: { color: "rgba(255,255,255,0.1)" }, ticks: { color: "#b8bcc8" } }
        }
      }
    });
  }

  async function loadRecentActivity() {
    const feed = $("#activityFeed");
    if (!feed) return;
    try {
      const res = await fetch("/api/recent-activity");
      const items = await res.json();
      if (!items?.length) {
        feed.innerHTML = `<div class="activity-item"><span class="activity-text">No recent activity</span><span class="activity-time">-</span></div>`;
        return;
      }
      feed.innerHTML = items.map(it => `
        <div class="activity-item">
          <span class="activity-text">${escapeHTML(it.type)}: ${escapeHTML(it.description)}</span>
          <span class="activity-time">${formatTime(it.created_at)}</span>
        </div>`).join("");
    } catch (e) {
      console.error("recent-activity error", e);
    }
  }

  function updateLastUpdated() {
    const el = $("#lastUpdated");
    if (el) el.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
  }
  function pulseKPI(ids){ ids.forEach(sel => { const v = $(sel); const card = v?.closest(".kpi-card"); if (!card) return; card.classList.add("pulse"); setTimeout(()=>card.classList.remove("pulse"), 900); }); }

  // ---------- Workers ----------
  function wireWorkerControls() {
    on($("#workerSearch"), "input", debounce(loadWorkers, 300));
    on($("#departmentFilter"), "change", loadWorkers);
    on($("#statusFilter"), "change", loadWorkers);
  }

  async function loadWorkers() {
    const tbody = $("#workersTable");
    if (!tbody) return;
    try {
      const search = ($("#workerSearch")?.value || "").trim();
      const department = $("#departmentFilter")?.value || "";
      const status = $("#statusFilter")?.value || "";
      const qs = new URLSearchParams({ search, department, status });
      const res = await fetch(`/api/workers?${qs.toString()}`);
      const data = await res.json();

      if (!data.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading">No workers found</td></tr>`;
        return;
      }
      tbody.innerHTML = data.map(w => {
        const badge = w.active ? `<span class="status-badge status-active">ACTIVE</span>` : `<span class="status-badge status-idle">INACTIVE</span>`;
        const qr = w.qrcode_path ? `<img src="${encodeURI(`/static/${w.qrcode_path}`)}" width="40" alt="QR">` : "No QR";
        return `
          <tr>
            <td>${escapeHTML(w.name || "")}</td>
            <td><code>${escapeHTML(w.token_id || "")}</code></td>
            <td><span class="department-tag">${escapeHTML(w.department || "N/A")}</span></td>
            <td>${escapeHTML(w.line || "N/A")}</td>
            <td>${badge}</td>
            <td>${qr}</td>
            <td>
              <a href="/edit/${w.id}" class="btn btn--primary btn-sm">Edit</a>
              <a href="/delete/${w.id}" class="btn btn--secondary btn-sm" onclick="return confirm('Delete this worker?');">Delete</a>
              ${w.qrcode_path ? `<a href="/download_qr/${w.id}" class="btn btn--outline btn-sm">Download QR</a>` : ""}
            </td>
          </tr>`;
      }).join("");
    } catch (e) {
      console.error("workers error", e);
      tbody.innerHTML = `<tr><td colspan="7" class="loading">Failed to load workers</td></tr>`;
    }
  }

  // ---------- Operations ----------
  function wireOperationControls() {
    on($("#operationSearch"), "input", debounce(loadOperations, 300));
  }
  async function loadOperations() {
    const tbody = $("#operationsTable");
    if (!tbody) return;
    try {
      const search = ($("#operationSearch")?.value || "").trim();
      const qs = new URLSearchParams(search ? { search } : {});
      const res = await fetch(`/api/operations?${qs.toString()}`);
      const rows = await res.json();
      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading">No operations found</td></tr>`;
        return;
      }
      tbody.innerHTML = rows.map(op => `
        <tr>
          <td>${op.seq_no ?? "-"}</td>
          <td><code>${escapeHTML(op.op_no || "")}</code></td>
          <td>${escapeHTML(op.description || "")}</td>
          <td>${escapeHTML(op.machine || "N/A")}</td>
          <td><span class="department-tag">${escapeHTML(op.department || "N/A")}</span></td>
          <td>${op.std_min ? `${op.std_min} min` : "N/A"}</td>
          <td>${op.piece_rate ? `₹${op.piece_rate}` : "N/A"}</td>
        </tr>`).join("");
    } catch (e) {
      console.error("operations error", e);
      tbody.innerHTML = `<tr><td colspan="7" class="loading">Failed to load operations</td></tr>`;
    }
  }

  // ---------- Bundles ----------
  async function loadBundles() {
    const grid = $("#bundlesGrid");
    if (!grid) return;
    try {
      const res = await fetch("/api/bundles");
      const rows = await res.json();
      if (!rows.length) {
        grid.innerHTML = `<div class="loading-card">No bundles found</div>`;
        return;
      }
      grid.innerHTML = rows.map(b => {
        const statusClass = String(b.status || "pending").toLowerCase().replace(/\s+/g, "-");
        return `
          <div class="bundle-card">
            <div class="bundle-header">
              <div class="bundle-id">${escapeHTML(b.bundle_no || "")}</div>
              <span class="status-badge status-${statusClass}">${escapeHTML(b.status || "Pending")}</span>
            </div>
            <div class="bundle-details">
              <div class="bundle-detail"><span>Style:</span><strong>${escapeHTML(b.style || "N/A")}</strong></div>
              <div class="bundle-detail"><span>Color:</span><strong>${escapeHTML(b.color || "N/A")}</strong></div>
              <div class="bundle-detail"><span>Size:</span><strong>${escapeHTML(b.size || "N/A")}</strong></div>
              <div class="bundle-detail"><span>Quantity:</span><strong>${b.quantity ?? "N/A"}</strong></div>
              <div class="bundle-detail"><span>Created:</span><strong>${formatDate(b.created_at)}</strong></div>
            </div>
          </div>`;
      }).join("");
    } catch (e) {
      console.error("bundles error", e);
      grid.innerHTML = `<div class="loading-card">Failed to load bundles</div>`;
    }
  }

  // ---------- Production Order ----------
  async function loadProductionOrder() {
    const elNo = $("#orderNo"), elStyle = $("#orderStyle"),
          elQty = $("#orderQuantity"), elBuyer = $("#orderBuyer");
    if (!elNo || !elStyle || !elQty || !elBuyer) return;
    try {
      const res = await fetch("/api/production-order");
      const order = await res.json();
      elNo.textContent = order.order_no || "No order found";
      elStyle.textContent = order.style || "N/A";
      elQty.textContent = isFinite(order.quantity) ? Number(order.quantity).toLocaleString() : "N/A";
      elBuyer.textContent = order.buyer || "N/A";
    } catch (e) {
      console.error("production-order error", e);
      elNo.textContent = "No order found"; elStyle.textContent = "N/A"; elQty.textContent = "N/A"; elBuyer.textContent = "N/A";
    }
  }

  // ---------- Scanner demo ----------
  function wireScanDemo() {
    const startBtn = $("#startScan"), stopBtn = $("#stopScan"), resetBtn = $("#resetScan");
    let scanning = false, timer = null;

    on(startBtn, "click", () => {
      if (scanning) return;
      scanning = true; setScanStatus("Scanning...");
      if (startBtn) startBtn.disabled = true; if (stopBtn) stopBtn.disabled = false;
      timer = setInterval(() => {
        const code = generateRandomCode();
        displayScanResult(code);
        prependScan(code);
      }, 3000);
    });

    on(stopBtn, "click", stop);
    on(resetBtn, "click", () => {
      stop(); setScanStatus("Ready to Scan");
      const list = $("#recentScans"); const result = $("#scanResult");
      if (list) list.innerHTML = '<div class="scan-item">No recent scans</div>';
      if (result) result.textContent = "";
    });

    function stop() {
      if (!scanning) return;
      scanning = false; clearInterval(timer); timer = null;
      if (startBtn) startBtn.disabled = false; if (stopBtn) stopBtn.disabled = true;
      setScanStatus("Stopped");
    }
  }
  function setScanStatus(t){ const el=$("#scannerStatus"); if(el) el.textContent=t; }
  function displayScanResult(code){ const el=$("#scanResult"); if(el){ el.textContent=code; el.style.animation="slideUp 0.5s"; setTimeout(()=>el.style.animation="",600);} }
  function prependScan(code){ const list=$("#recentScans"); if(list){ list.insertAdjacentHTML("afterbegin",`<div class="scan-item"><span class="scan-code">${escapeHTML(code)}</span><span class="scan-time">${new Date().toLocaleTimeString()}</span></div>`);} }
  function generateRandomCode(){ const p=["W","B","O"]; const pre=p[Math.floor(Math.random()*p.length)]; const n=String(Math.floor(Math.random()*999)+1).padStart(3,"0"); return `${pre}${n}`; }

  // ---------- utils ----------
  function debounce(fn, w=300){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn.apply(null,a),w); }; }
  function setText(sel, val){ const el=$(sel); if(el) el.textContent=val; }
  function formatDate(s){ if(!s) return "N/A"; const d=new Date(s); return isNaN(d)?s:d.toLocaleDateString("en-US",{year:"numeric",month:"short",day:"numeric"}); }
  function formatTime(s){ if(!s) return "N/A"; const d=new Date(s), n=new Date(); const m=Math.floor((n-d)/60000); if(m<1) return "Just now"; if(m<60) return `${m}m ago`; const h=Math.floor(m/60); if(h<24) return `${h}h ago`; const dd=Math.floor(h/24); return `${dd}d ago`; }
  function escapeHTML(str){ return String(str).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;"); }
})();
