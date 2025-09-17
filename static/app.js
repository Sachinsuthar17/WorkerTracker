/* Production Management System - Frontend Logic */

document.addEventListener("DOMContentLoaded", () => {
  // ====== SIDEBAR NAV ======
  const sidebar = document.getElementById("sidebar");
  const sidebarToggle = document.getElementById("sidebarToggle");
  const navItems = document.querySelectorAll(".nav-item");
  const sections = document.querySelectorAll(".section");

  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
      sidebar.classList.toggle("active");
    });
  }

  navItems.forEach(item => {
    item.addEventListener("click", e => {
      e.preventDefault();
      navItems.forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      const target = item.dataset.section;
      sections.forEach(sec => {
        sec.classList.toggle("active", sec.id === target);
      });
      // also update hash so deep-links work
      if (target) location.hash = target;
    });
  });

  // NEW: allow deep-links like /#workers and the sidebar links from add/edit pages
  function activateSectionFromHash() {
    const hash = (location.hash || "#dashboard").replace("#", "");
    const target = document.getElementById(hash);
    if (!target) return;

    // switch visible section
    sections.forEach(sec => sec.classList.toggle("active", sec === target));

    // update left nav state if present
    document.querySelectorAll('.nav-item').forEach(a => a.classList.remove('active'));
    const match = document.querySelector(`.nav-item[data-section="${hash}"]`);
    if (match) match.classList.add('active');
  }

  window.addEventListener("hashchange", activateSectionFromHash);

  // ====== DASHBOARD ======
  async function loadDashboard() {
    try {
      const res = await fetch("/api/dashboard-stats");
      const data = await res.json();

      if (document.getElementById("activeWorkers"))
        document.getElementById("activeWorkers").textContent = data.activeWorkers;
      if (document.getElementById("totalBundles"))
        document.getElementById("totalBundles").textContent = data.totalBundles;
      if (document.getElementById("totalOperations"))
        document.getElementById("totalOperations").textContent = data.totalOperations;
      if (document.getElementById("totalEarnings"))
        document.getElementById("totalEarnings").textContent = data.totalEarnings.toFixed(2);

      loadCharts();
      loadRecentActivity();
    } catch (err) {
      console.error("dashboard load error", err);
    }
  }

  async function loadCharts() {
    try {
      const res = await fetch("/api/chart-data");
      const data = await res.json();

      const bundleCtx = document.getElementById("bundleChart");
      if (bundleCtx) {
        new Chart(bundleCtx, {
          type: "doughnut",
          data: {
            labels: Object.keys(data.bundleStatus),
            datasets: [{ data: Object.values(data.bundleStatus), backgroundColor: ["#3b82f6", "#f59e0b", "#10b981", "#ef4444"] }]
          },
          options: { responsive: true, plugins: { legend: { position: "bottom" } } }
        });
      }

      const deptCtx = document.getElementById("departmentChart");
      if (deptCtx) {
        new Chart(deptCtx, {
          type: "bar",
          data: {
            labels: Object.keys(data.departmentWorkload),
            datasets: [{ label: "Workers", data: Object.values(data.departmentWorkload), backgroundColor: "#8b5cf6" }]
          },
          options: { responsive: true, scales: { y: { beginAtZero: true } } }
        });
      }
    } catch (err) {
      console.error("chart error", err);
    }
  }

  async function loadRecentActivity() {
    try {
      const res = await fetch("/api/recent-activity");
      const data = await res.json();
      const feed = document.getElementById("activityFeed");
      if (feed) {
        feed.innerHTML = "";
        data.forEach(item => {
          const div = document.createElement("div");
          div.className = "activity-item";
          div.innerHTML = `
            <span class="activity-text">${item.type}: ${item.description}</span>
            <span class="activity-time">${item.created_at}</span>`;
          feed.appendChild(div);
        });
      }
    } catch (err) {
      console.error("activity error", err);
    }
  }

  // ====== WORKERS ======
  const workerSearch = document.getElementById("workerSearch");
  const deptFilter = document.getElementById("departmentFilter");
  const statusFilter = document.getElementById("statusFilter");
  const workersTable = document.getElementById("workersTable");

  async function loadWorkers() {
    try {
      const search = workerSearch?.value || "";
      const department = deptFilter?.value || "";
      const status = statusFilter?.value || "";
      const params = new URLSearchParams({ search, department, status });
      const res = await fetch(`/api/workers?${params.toString()}`);
      const data = await res.json();

      if (workersTable) {
        workersTable.innerHTML = "";
        if (data.length === 0) {
          workersTable.innerHTML = `<tr><td colspan="7" class="loading">No workers found</td></tr>`;
          return;
        }
        data.forEach(w => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${w.name}</td>
            <td>${w.token_id}</td>
            <td>${w.department}</td>
            <td>${w.line || "N/A"}</td>
            <td><span class="status-badge ${w.active ? "status-active" : "status-idle"}">${w.active ? "ACTIVE" : "INACTIVE"}</span></td>
            <td>${w.qrcode_path ? `<img src="/static/${w.qrcode_path}" width="40" alt="QR">` : "No QR"}</td>
            <td>
              <a href="/edit/${w.id}" class="btn btn--primary btn-sm">Edit</a>
              <a href="/delete/${w.id}" class="btn btn--secondary btn-sm" onclick="return confirm('Delete this worker?');">Delete</a>
              ${w.qrcode_path ? `<a href="/download_qr/${w.id}" class="btn btn--outline btn-sm">Download QR</a>` : ""}
            </td>`;
          workersTable.appendChild(tr);
        });
      }
    } catch (err) {
      console.error("workers error", err);
    }
  }

  workerSearch?.addEventListener("input", loadWorkers);
  deptFilter?.addEventListener("change", loadWorkers);
  statusFilter?.addEventListener("change", loadWorkers);

  // ====== OPERATIONS ======
  async function loadOperations() {
    try {
      const res = await fetch("/api/operations");
      const data = await res.json();
      const table = document.getElementById("operationsTable");
      if (table) {
        table.innerHTML = "";
        data.forEach(op => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${op.seq_no || ""}</td>
            <td>${op.op_no || ""}</td>
            <td>${op.description || ""}</td>
            <td>${op.machine || ""}</td>
            <td>${op.department || ""}</td>
            <td>${op.std_min || ""}</td>
            <td>${op.piece_rate || ""}</td>`;
          table.appendChild(tr);
        });
      }
    } catch (err) {
      console.error("operations error", err);
    }
  }

  // ====== BUNDLES ======
  async function loadBundles() {
    try {
      const res = await fetch("/api/bundles");
      const data = await res.json();
      const container = document.getElementById("bundlesGrid");
      if (container) {
        container.innerHTML = "";
        data.forEach(b => {
          const div = document.createElement("div");
          div.className = "bundle-card";
          div.innerHTML = `
            <div class="bundle-header">
              <span class="bundle-id">Bundle ${b.bundle_no}</span>
              <span class="status-badge status-${b.status.toLowerCase()}">${b.status}</span>
            </div>
            <div class="bundle-details">
              <div class="bundle-detail"><strong>Order:</strong> <span>${b.order_no}</span></div>
              <div class="bundle-detail"><strong>Style:</strong> <span>${b.style}</span></div>
              <div class="bundle-detail"><strong>Color:</strong> <span>${b.color}</span></div>
              <div class="bundle-detail"><strong>Size:</strong> <span>${b.size}</span></div>
              <div class="bundle-detail"><strong>Qty:</strong> <span>${b.quantity}</span></div>
            </div>`;
          container.appendChild(div);
        });
      }
    } catch (err) {
      console.error("bundles error", err);
    }
  }

  // ====== PRODUCTION ORDER ======
  async function loadProductionOrder() {
    try {
      const res = await fetch("/api/production-order");
      const data = await res.json();
      const container = document.getElementById("productionOrder");
      if (container && data.order_no) {
        container.innerHTML = `
          <p><strong>Order No:</strong> ${data.order_no}</p>
          <p><strong>Style:</strong> ${data.style}</p>
          <p><strong>Quantity:</strong> ${data.quantity}</p>
          <p><strong>Buyer:</strong> ${data.buyer}</p>`;
      }
    } catch (err) {
      console.error("production order error", err);
    }
  }

  // ====== simple scan demo (unchanged) ======
  const scanBtn = document.getElementById("simulateScanBtn");
  const scanResult = document.getElementById("scanResult");
  const scansList = document.getElementById("scansList");
  scanBtn?.addEventListener("click", () => {
    const code = `CODE-${Math.floor(Math.random() * 10000)}`;
    const time = new Date().toLocaleTimeString();
    scanResult.textContent = code;
    const div = document.createElement("div");
    div.className = "scan-item";
    div.innerHTML = `<span class="scan-code">${code}</span><span class="scan-time">${time}</span>`;
    scansList.prepend(div);
  });

  // ====== INIT LOAD ======
  // perform data loads once
  loadDashboard();
  loadWorkers();
  loadOperations();
  loadBundles();
  loadProductionOrder();

  // activate section based on current hash
  activateSectionFromHash();
});
