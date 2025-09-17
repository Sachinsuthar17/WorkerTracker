/* Production Management System - Frontend Logic (revised, safe on all pages) */

(() => {
  // ------------- helpers -------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const on = (el, ev, fn) => el && el.addEventListener(ev, fn);

  let autoRefreshTimer = null;
  let charts = {
    bundle: null,
    department: null,
  };

  // ------------- sidebar & SPA sections (only if present) -------------
  document.addEventListener("DOMContentLoaded", () => {
    const sidebar = $("#sidebar");
    const sidebarToggle = $("#sidebarToggle");
    const navItems = $$(".nav-item");
    const sections = $$(".section");

    // Toggle sidebar (mobile)
    on(sidebarToggle, "click", () => sidebar?.classList.toggle("active"));

    // Handle nav clicks only if we’re on the index page (sections exist)
    if (sections.length) {
      navItems.forEach(item => {
        on(item, "click", e => {
          e.preventDefault();
          const target = item.dataset.section;
          if (!target) return;
          // update hash -> this also allows deep links and back/forward
          if (location.hash !== `#${target}`) {
            location.hash = target;
          } else {
            activateSection(target);
          }
          // close sidebar on mobile
          if (window.innerWidth <= 768) sidebar?.classList.remove("active");
        });
      });

      // initial activation + load
      activateSectionFromHash();
      loadSectionData(currentSectionId());

      // update on hash changes
      window.addEventListener("hashchange", () => {
        activateSectionFromHash();
        loadSectionData(currentSectionId());
      });
    }

    // Attach listeners for controls (guarded by existence)
    wireDashboardControls();
    wireWorkerControls();
    wireOperationControls();
    wireScanDemo();

    // If there are no sections (e.g., add/edit pages), do nothing else.
  });

  // ------------- SPA helpers -------------
  function currentSectionId() {
    return (location.hash || "#dashboard").replace("#", "");
  }

  function activateSectionFromHash() {
    const id = currentSectionId();
    activateSection(id);
  }

  function activateSection(id) {
    const sections = $$(".section");
    const navItems = $$(".nav-item");
    if (!sections.length) return;

    // set section visibility
    sections.forEach(sec => sec.classList.toggle("active", sec.id === id));

    // set nav active state
    navItems.forEach(i => i.classList.remove("active"));
    const activeNav = $(`.nav-item[data-section="${id}"]`);
    activeNav?.classList.add("active");

    manageAutoRefresh(id);
  }

  function manageAutoRefresh(sectionId) {
    if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer);
      autoRefreshTimer = null;
    }
    if (sectionId === "dashboard") {
      // refresh dashboard KPIs & activity every 30s
      autoRefreshTimer = setInterval(() => {
        loadDashboardStats();
        loadRecentActivity();
        updateLastUpdated();
      }, 30000);
    }
  }

  function loadSectionData(sectionId) {
    switch (sectionId) {
      case "dashboard":
        loadDashboard();
        break;
      case "workers":
        loadWorkers();
        break;
      case "operations":
        loadOperations();
        break;
      case "bundles":
        loadBundles();
        break;
      case "production-order":
        loadProductionOrder();
        break;
      case "scanner":
        // purely UI demo for now
        break;
      default:
        break;
    }
  }

  // ------------- Dashboard -------------
  function wireDashboardControls() {
    const btn = $("#refreshBtn");
    on(btn, "click", async () => {
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Refreshing...";
      await loadDashboard();
      btn.disabled = false;
      btn.textContent = original || "Refresh";
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
    } catch (err) {
      console.error("dashboard-stats error", err);
      setText("#activeWorkers", "0");
      setText("#totalBundles", "0");
      setText("#totalOperations", "0");
      setText("#totalEarnings", "₹0.00");
    }
  }

  async function loadChartData() {
    try {
      const res = await fetch("/api/chart-data");
      const data = await res.json();
      updateBundleChart(data.bundleStatus || {});
      updateDepartmentChart(data.departmentWorkload || {});
    } catch (err) {
      console.error("chart-data error", err);
      // fallback demo data
      updateBundleChart({ Pending: 3, "In Progress": 5, Completed: 6 });
      updateDepartmentChart({ Cutting: 8, Sewing: 12, Finishing: 6, Quality: 4, Packing: 3 });
    }
  }

  function updateBundleChart(statusMap) {
    const el = $("#bundleStatusChart") || $("#bundleChart"); // support both IDs
    if (!el || !window.Chart) return;

    if (charts.bundle) {
      charts.bundle.destroy();
      charts.bundle = null;
    }

    const labels = Object.keys(statusMap);
    const values = Object.values(statusMap);

    charts.bundle = new Chart(el, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: ["#f59e0b", "#3b82f6", "#10b981", "#ef4444"],
            borderWidth: 0,
            hoverOffset: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function updateDepartmentChart(deptMap) {
    const el = $("#departmentChart");
    if (!el || !window.Chart) return;

    if (charts.department) {
      charts.department.destroy();
      charts.department = null;
    }

    const labels = Object.keys(deptMap);
    const values = Object.values(deptMap);

    charts.department = new Chart(el, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Workers",
            data: values,
            backgroundColor: "rgba(59,130,246,0.8)",
            borderColor: "#3b82f6",
            borderWidth: 1,
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            grid: { color: "rgba(255,255,255,0.1)" },
            ticks: { color: "#b8bcc8" },
          },
          y: {
            beginAtZero: true,
            grid: { color: "rgba(255,255,255,0.1)" },
            ticks: { color: "#b8bcc8" },
          },
        },
      },
    });
  }

  async function loadRecentActivity() {
    try {
      const res = await fetch("/api/recent-activity");
      const items = await res.json();
      const feed = $("#activityFeed");
      if (!feed) return;

      if (!items || !items.length) {
        feed.innerHTML = `
          <div class="activity-item">
            <span class="activity-text">No recent activity</span>
            <span class="activity-time">-</span>
          </div>`;
        return;
      }

      feed.innerHTML = items
        .map(
          (it) => `
          <div class="activity-item">
            <span class="activity-text">${escapeHTML(it.type)}: ${escapeHTML(it.description)}</span>
            <span class="activity-time">${formatTime(it.created_at)}</span>
          </div>`
        )
        .join("");
    } catch (err) {
      console.error("recent-activity error", err);
    }
  }

  function updateLastUpdated() {
    const el = $("#lastUpdated");
    if (el) el.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
  }

  function pulseKPI(ids) {
    ids.forEach((sel) => {
      const valueEl = $(sel);
      const card = valueEl?.closest(".kpi-card");
      if (!card) return;
      card.classList.add("pulse");
      setTimeout(() => card.classList.remove("pulse"), 900);
    });
  }

  // ------------- Workers -------------
  function wireWorkerControls() {
    const search = $("#workerSearch");
    const dept = $("#departmentFilter");
    const status = $("#statusFilter");
    on(search, "input", debounce(loadWorkers, 300));
    on(dept, "change", loadWorkers);
    on(status, "change", loadWorkers);
  }

  async function loadWorkers() {
    const tbody = $("#workersTable");
    if (!tbody) return; // not on workers section page

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

      tbody.innerHTML = data
        .map((w) => {
          const statusBadge = w.active
            ? `<span class="status-badge status-active">ACTIVE</span>`
            : `<span class="status-badge status-idle">INACTIVE</span>`;
          const qrCell = w.qrcode_path
            ? `<img src="${encodeURI(`/static/${w.qrcode_path}`)}" width="40" alt="QR">`
            : "No QR";
          const actions = `
            <a href="/edit/${w.id}" class="btn btn--primary btn-sm">Edit</a>
            <a href="/delete/${w.id}" class="btn btn--secondary btn-sm" onclick="return confirm('Delete this worker?');">Delete</a>
            ${w.qrcode_path ? `<a href="/download_qr/${w.id}" class="btn btn--outline btn-sm">Download QR</a>` : ""}`;

          return `
            <tr>
              <td>${escapeHTML(w.name || "")}</td>
              <td><code>${escapeHTML(w.token_id || "")}</code></td>
              <td><span class="department-tag">${escapeHTML(w.department || "N/A")}</span></td>
              <td>${escapeHTML(w.line || "N/A")}</td>
              <td>${statusBadge}</td>
              <td>${qrCell}</td>
              <td>${actions}</td>
            </tr>`;
        })
        .join("");
    } catch (err) {
      console.error("workers error", err);
      tbody.innerHTML = `<tr><td colspan="7" class="loading">Failed to load workers</td></tr>`;
    }
  }

  // ------------- Operations -------------
  function wireOperationControls() {
    const opSearch = $("#operationSearch");
    on(opSearch, "input", debounce(loadOperations, 300));
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

      tbody.innerHTML = rows
        .map(
          (op) => `
          <tr>
            <td>${op.seq_no ?? "-"}</td>
            <td><code>${escapeHTML(op.op_no || "")}</code></td>
            <td>${escapeHTML(op.description || "")}</td>
            <td>${escapeHTML(op.machine || "N/A")}</td>
            <td><span class="department-tag">${escapeHTML(op.department || "N/A")}</span></td>
            <td>${op.std_min ? `${op.std_min} min` : "N/A"}</td>
            <td>${op.piece_rate ? `₹${op.piece_rate}` : "N/A"}</td>
          </tr>`
        )
        .join("");
    } catch (err) {
      console.error("operations error", err);
      tbody.innerHTML = `<tr><td colspan="7" class="loading">Failed to load operations</td></tr>`;
    }
  }

  // ------------- Bundles -------------
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

      grid.innerHTML = rows
        .map((b) => {
          const statusClass = String(b.status || "")
            .toLowerCase()
            .replace(/\s+/g, "-");
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
        })
        .join("");
    } catch (err) {
      console.error("bundles error", err);
      grid.innerHTML = `<div class="loading-card">Failed to load bundles</div>`;
    }
  }

  // ------------- Production Order -------------
  async function loadProductionOrder() {
    const elNo = $("#orderNo");
    const elStyle = $("#orderStyle");
    const elQty = $("#orderQuantity");
    const elBuyer = $("#orderBuyer");
    // Only run if those fields exist
    if (!elNo || !elStyle || !elQty || !elBuyer) return;

    try {
      const res = await fetch("/api/production-order");
      const order = await res.json();

      elNo.textContent = order.order_no || "No order found";
      elStyle.textContent = order.style || "N/A";
      elQty.textContent = isFinite(order.quantity) ? Number(order.quantity).toLocaleString() : "N/A";
      elBuyer.textContent = order.buyer || "N/A";
    } catch (err) {
      console.error("production-order error", err);
      elNo.textContent = "No order found";
      elStyle.textContent = "N/A";
      elQty.textContent = "N/A";
      elBuyer.textContent = "N/A";
    }
  }

  // ------------- Scanner (pure UI demo; no backend calls) -------------
  function wireScanDemo() {
    const startBtn = $("#startScan");
    const stopBtn = $("#stopScan");
    const resetBtn = $("#resetScan");

    let scanning = false;
    let timer = null;

    on(startBtn, "click", () => {
      if (scanning) return;
      scanning = true;
      setScanStatus("Scanning...");
      startBtn.disabled = true;
      stopBtn && (stopBtn.disabled = false);

      timer = setInterval(() => {
        const code = generateRandomCode();
        displayScanResult(code);
        prependScan(code);
      }, 3000);
    });

    on(stopBtn, "click", () => stop());
    on(resetBtn, "click", () => {
      stop();
      setScanStatus("Ready to Scan");
      const list = $("#recentScans");
      const result = $("#scanResult");
      if (list) list.innerHTML = '<div class="scan-item">No recent scans</div>';
      if (result) result.textContent = "";
    });

    function stop() {
      if (!scanning) return;
      scanning = false;
      clearInterval(timer);
      timer = null;
      const start = $("#startScan");
      const stopB = $("#stopScan");
      start && (start.disabled = false);
      stopB && (stopB.disabled = true);
      setScanStatus("Stopped");
    }
  }

  function setScanStatus(txt) {
    const el = $("#scannerStatus");
    if (el) el.textContent = txt;
  }

  function displayScanResult(code) {
    const el = $("#scanResult");
    if (el) {
      el.textContent = code;
      el.style.animation = "slideUp 0.5s ease-in-out";
      setTimeout(() => (el.style.animation = ""), 600);
    }
  }

  function prependScan(code) {
    const list = $("#recentScans");
    if (!list) return;
    const html = `
      <div class="scan-item">
        <span class="scan-code">${escapeHTML(code)}</span>
        <span class="scan-time">${new Date().toLocaleTimeString()}</span>
      </div>`;
    list.insertAdjacentHTML("afterbegin", html);
  }

  function generateRandomCode() {
    const prefixes = ["W", "B", "O"];
    const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
    const number = String(Math.floor(Math.random() * 999) + 1).padStart(3, "0");
    return `${prefix}${number}`;
  }

  // ------------- utilities -------------
  function debounce(fn, wait = 300) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  function setText(sel, val) {
    const el = $(sel);
    if (el) el.textContent = val;
  }

  function formatDate(s) {
    if (!s) return "N/A";
    const d = new Date(s);
    if (isNaN(d)) return s;
    return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
    }

  function formatTime(s) {
    if (!s) return "N/A";
    const d = new Date(s);
    const now = new Date();
    const diffMin = Math.floor((now - d) / 60000);
    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    const diffD = Math.floor(diffH / 24);
    return `${diffD}d ago`;
  }

  function escapeHTML(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
