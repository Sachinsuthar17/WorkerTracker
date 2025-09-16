# static/app.js (Your Attached JS - Copy and Paste this Entire File)

// Production Management System - JavaScript
document.addEventListener('DOMContentLoaded', function() {
  // Initialize the application
  initializeApp();
});

// Global variables
let currentSection = 'dashboard';
let isScanning = false;
let scanInterval;
let refreshInterval;

// Charts
let bundleStatusChart = null;
let departmentChart = null;

// Initialize application
function initializeApp() {
  setupEventListeners();
  setupMobileMenu();
  loadDashboard();
  startAutoRefresh();
  console.log('Production Management System initialized');
}

// Setup all event listeners
function setupEventListeners() {
  // Navigation
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', handleNavigation);
  });

  // Dashboard refresh
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', refreshDashboard);
  }

  // Search inputs
  const workerSearch = document.getElementById('workerSearch');
  if (workerSearch) {
    workerSearch.addEventListener('input', debounce(searchWorkers, 300));
  }

  const operationSearch = document.getElementById('operationSearch');
  if (operationSearch) {
    operationSearch.addEventListener('input', debounce(searchOperations, 300));
  }

  // Filters
  const departmentFilter = document.getElementById('departmentFilter');
  if (departmentFilter) {
    departmentFilter.addEventListener('change', searchWorkers);
  }

  const statusFilter = document.getElementById('statusFilter');
  if (statusFilter) {
    statusFilter.addEventListener('change', searchWorkers);
  }

  // File uploads
  setupFileUploads();

  // Scanner controls
  setupScannerControls();
}

// Setup mobile menu
function setupMobileMenu() {
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.toggle('active');
    });

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', (e) => {
      if (window.innerWidth <= 768 && !sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
        sidebar.classList.remove('active');
      }
    });
  }
}

// Handle navigation between sections
function handleNavigation(e) {
  e.preventDefault();
  const section = e.currentTarget.dataset.section;
  if (section === currentSection) return;

  // Update nav items
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.remove('active');
  });
  e.currentTarget.classList.add('active');

  // Show/hide sections
  document.querySelectorAll('.section').forEach(sec => {
    sec.classList.remove('active');
  });
  const targetSection = document.getElementById(section);
  if (targetSection) {
    targetSection.classList.add('active');
    currentSection = section;

    // Load section data
    loadSectionData(section);

    // Close mobile menu
    if (window.innerWidth <= 768) {
      document.getElementById('sidebar').classList.remove('active');
    }
  }
}

// Load data for specific section
function loadSectionData(section) {
  switch (section) {
    case 'dashboard':
      loadDashboard();
      break;
    case 'workers':
      loadWorkers();
      break;
    case 'operations':
      loadOperations();
      break;
    case 'bundles':
      loadBundles();
      break;
    case 'production-order':
      loadProductionOrder();
      break;
    case 'scanner':
      loadRecentScans();
      break;
  }
}

// Dashboard functions
async function loadDashboard() {
  try {
    await Promise.all([
      loadDashboardStats(),
      loadChartData(),
      loadRecentActivity()
    ]);
  } catch (error) {
    console.error('Error loading dashboard:', error);
  }
}

async function loadDashboardStats() {
  try {
    const response = await fetch('/api/dashboard-stats');
    const stats = await response.json();
    updateKPICard('activeWorkers', stats.activeWorkers);
    updateKPICard('totalBundles', stats.totalBundles);
    updateKPICard('totalOperations', stats.totalOperations);
    updateKPICard('totalEarnings', `₹${stats.totalEarnings.toFixed(2)}`);
  } catch (error) {
    console.error('Error loading dashboard stats:', error);
    // Set default values
    updateKPICard('activeWorkers', '0');
    updateKPICard('totalBundles', '0');
    updateKPICard('totalOperations', '0');
    updateKPICard('totalEarnings', '₹0.00');
  }
}

function updateKPICard(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
    element.parentElement.parentElement.classList.add('pulse');
    setTimeout(() => {
      element.parentElement.parentElement.classList.remove('pulse');
    }, 1000);
  }
}

async function loadChartData() {
  try {
    const response = await fetch('/api/chart-data');
    const data = await response.json();
    updateBundleStatusChart(data.bundleStatus || {});
    updateDepartmentChart(data.departmentWorkload || {});
  } catch (error) {
    console.error('Error loading chart data:', error);
    // Load with sample data
    updateBundleStatusChart({ 'Pending': 3, 'In Progress': 5, 'Completed': 6 });
    updateDepartmentChart({ 'Cutting': 8, 'Sewing': 12, 'Finishing': 6, 'Quality': 4, 'Packing': 3 });
  }
}

function updateBundleStatusChart(data) {
  const ctx = document.getElementById('bundleStatusChart');
  if (!ctx) return;
  if (bundleStatusChart) {
    bundleStatusChart.destroy();
  }
  const labels = Object.keys(data);
  const values = Object.values(data);
  const colors = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444'];
  bundleStatusChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderWidth: 0,
        hoverOffset: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#b8bcc8',
            padding: 20,
            usePointStyle: true
          }
        }
      }
    }
  });
}

function updateDepartmentChart(data) {
  const ctx = document.getElementById('departmentChart');
  if (!ctx) return;
  if (departmentChart) {
    departmentChart.destroy();
  }
  const labels = Object.keys(data);
  const values = Object.values(data);
  departmentChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Workers',
        data: values,
        backgroundColor: 'rgba(59, 130, 246, 0.8)',
        borderColor: '#3b82f6',
        borderWidth: 1,
        borderRadius: 8
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        }
      },
      scales: {
        x: {
          grid: {
            color: 'rgba(255, 255, 255, 0.1)'
          },
          ticks: {
            color: '#b8bcc8'
          }
        },
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(255, 255, 255, 0.1)'
          },
          ticks: {
            color: '#b8bcc8'
          }
        }
      }
    }
  });
}

async function loadRecentActivity() {
  try {
    const response = await fetch('/api/recent-activity');
    const activities = await response.json();
    const activityFeed = document.getElementById('activityFeed');
    if (activityFeed) {
      if (activities.length === 0) {
        activityFeed.innerHTML = '<p class="no-data">No recent activity</p>';
      } else {
        activityFeed.innerHTML = activities.map(activity => `
          <div class="activity-item">
            <span class="activity-text">${activity.type}: ${activity.description}</span>
            <span class="activity-time">${new Date(activity.created_at).toLocaleString()}</span>
          </div>
        `).join('');
      }
    }
  } catch (error) {
    console.error('Error loading recent activity:', error);
    const activityFeed = document.getElementById('activityFeed');
    if (activityFeed) {
      activityFeed.innerHTML = '<p class="error">Error loading activity</p>';
    }
  }
}

// Workers functions
async function loadWorkers() {
  try {
    const response = await fetch('/api/workers');
    const workers = await response.json();
    const tableBody = document.getElementById('workersTableBody');
    if (tableBody) {
      tableBody.innerHTML = workers.map(worker => `
        <tr>
          <td>${worker.name}</td>
          <td>${worker.token_id}</td>
          <td><span class="department-tag">${worker.department}</span></td>
          <td>${worker.line}</td>
          <td><span class="status-badge status-${worker.status.toLowerCase()}">${worker.status}</span></td>
          <td>
            <button class="btn btn-sm btn--outline" onclick="showQrCode('${worker.qr_code}', '${worker.name}')">View QR</button>
          </td>
          <td>
            <button class="btn btn-sm btn--secondary">Edit</button>
          </td>
        </tr>
      `).join('');
    }
  } catch (error) {
    console.error('Error loading workers:', error);
  }
}

function searchWorkers() {
  // Implement search logic here
  console.log('Searching workers...');
}

// Operations functions
async function loadOperations() {
  try {
    const response = await fetch('/api/operations');
    const operations = await response.json();
    const tableBody = document.getElementById('operationsTableBody');
    if (tableBody) {
      tableBody.innerHTML = operations.map(op => `
        <tr>
          <td>${op.seq_no}</td>
          <td>${op.op_no}</td>
          <td>${op.description}</td>
          <td>${op.machine}</td>
          <td>${op.department}</td>
          <td>${op.std_min}</td>
          <td>₹${op.piece_rate.toFixed(2)}</td>
        </tr>
      `).join('');
    }
  } catch (error) {
    console.error('Error loading operations:', error);
  }
}

function searchOperations() {
  // Implement search logic here
  console.log('Searching operations...');
}

// Bundles functions
async function loadBundles() {
  try {
    const response = await fetch('/api/bundles');
    const bundles = await response.json();
    const bundlesGrid = document.getElementById('bundlesGrid');
    if (bundlesGrid) {
      bundlesGrid.innerHTML = bundles.map(bundle => `
        <div class="bundle-card">
          <div class="bundle-header">
            <h3 class="bundle-id">${bundle.bundle_no}</h3>
            <span class="status-badge status-${bundle.status.toLowerCase().replace(' ', '-')}">${bundle.status}</span>
          </div>
          <div class="bundle-details">
            <p><strong>Order No:</strong> ${bundle.order_no}</p>
            <p><strong>Style:</strong> ${bundle.style}</p>
            <p><strong>Color:</strong> ${bundle.color}</p>
            <p><strong>Size:</strong> ${bundle.size}</p>
            <p><strong>Quantity:</strong> ${bundle.quantity}</p>
          </div>
        </div>
      `).join('');
    }
  } catch (error) {
    console.error('Error loading bundles:', error);
  }
}

// Production Order functions
async function loadProductionOrder() {
  try {
    const response = await fetch('/api/production-order');
    const order = await response.json();
    document.getElementById('orderNo').textContent = order.order_no || 'N/A';
    document.getElementById('styleName').textContent = order.style || 'N/A';
    document.getElementById('totalQty').textContent = order.quantity || '0';
    document.getElementById('buyerName').textContent = order.buyer || 'N/A';
    // Color distribution can be added if available in API
  } catch (error) {
    console.error('Error loading production order:', error);
  }
}

// File Uploads
function setupFileUploads() {
  setupUploadArea('obUploadArea', 'obFileInput', 'obUploadStatus', 'excel');
  setupUploadArea('poUploadArea', 'poFileInput', 'poUploadStatus', 'pdf');
}

function setupUploadArea(areaId, inputId, statusId, type) {
  const uploadArea = document.getElementById(areaId);
  const fileInput = document.getElementById(inputId);
  const uploadStatus = document.getElementById(statusId);

  if (uploadArea && fileInput) {
    uploadArea.addEventListener('click', () => fileInput.click());
    uploadArea.addEventListener('dragover', e => {
      e.preventDefault();
      uploadArea.classList.add('dragover');
    });
    uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
    uploadArea.addEventListener('drop', e => {
      e.preventDefault();
      uploadArea.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file) {
        handleFileUpload(file, type, statusId);
      }
    });
    fileInput.addEventListener('change', e => {
      const file = e.target.files[0];
      if (file) {
        handleFileUpload(file, type, statusId);
      }
    });
  }
}

async function handleFileUpload(file, type, statusId) {
  const uploadStatus = document.getElementById(statusId);
  if (uploadStatus) {
    uploadStatus.innerHTML = '<p class="uploading">Uploading...</p>';
  }
  const formData = new FormData();
  formData.append('file', file);
  formData.append('type', type);
  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    const result = await response.json();
    if (result.success) {
      uploadStatus.innerHTML = '<p class="upload-success">✅ File uploaded successfully!</p>';
    } else {
      uploadStatus.innerHTML = '<p class="upload-error">❌ Error: ' + result.error + '</p>';
    }
  } catch (error) {
    console.error('Upload error:', error);
    uploadStatus.innerHTML = '<p class="upload-error">❌ Upload failed. Please try again.</p>';
  }
}

// Scanner controls
function setupScannerControls() {
  const simulateBtn = document.getElementById('simulateScanBtn');
  if (simulateBtn) {
    simulateBtn.addEventListener('click', simulateScan);
  }
  const resetBtn = document.getElementById('resetScannerBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', resetScanner);
  }
}

function simulateScan() {
  if (isScanning) return;
  isScanning = true;
  document.getElementById('scanStatus').textContent = 'Scanning...';
  scanInterval = setInterval(() => {
    const fakeCode = 'SCAN-' + Math.random().toString(36).substr(2, 8).toUpperCase();
    addScanEntry(fakeCode);
  }, 2000);
  setTimeout(() => {
    clearInterval(scanInterval);
    isScanning = false;
    document.getElementById('scanStatus').textContent = 'Scan complete';
  }, 10000);
}

function resetScanner() {
  clearInterval(scanInterval);
  isScanning = false;
  document.getElementById('scanStatus').textContent = 'Ready to scan...';
  document.getElementById('scanLog').innerHTML = '';
}

function addScanEntry(code) {
  const scanLog = document.getElementById('scanLog');
  if (scanLog) {
    const entry = document.createElement('div');
    entry.className = 'scan-item';
    entry.innerHTML = `
      <span class="scan-code">${code}</span>
      <span class="scan-time">${new Date().toLocaleString()}</span>
    `;
    scanLog.prepend(entry);
  }
}

// Recent Scans
async function loadRecentScans() {
  try {
    const response = await fetch('/api/scans');
    const scans = await response.json();
    const scanLog = document.getElementById('scanLog');
    if (scanLog) {
      scanLog.innerHTML = scans.map(scan => `
        <div class="scan-item">
          <span class="scan-code">${scan.code}</span>
          <span class="scan-time">${new Date(scan.created_at).toLocaleString()}</span>
        </div>
      `).join('');
    }
  } catch (error) {
    console.error('Error loading recent scans:', error);
  }
}

// Auto refresh
function startAutoRefresh() {
  refreshInterval = setInterval(() => {
    if (currentSection === 'dashboard') {
      loadDashboard();
    }
  }, 30000); // Refresh every 30 seconds
}

// Debounce function
function debounce(func, delay) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), delay);
  };
}

// Refresh dashboard
function refreshDashboard() {
  loadDashboard();
  document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
}

// Initial load
refreshDashboard();

// Sidebar toggle for mobile
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebar = document.getElementById('sidebar');
if (sidebarToggle && sidebar) {
  sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('active'));
}

// Close sidebar on outside click for mobile
document.addEventListener('click', (e) => {
  if (window.innerWidth <= 768 && !sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
    sidebar.classList.remove('active');
  }
});
</script>
</body>
</html>
