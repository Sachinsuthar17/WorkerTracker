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
            if (window.innerWidth <= 768 && 
                !sidebar.contains(e.target) && 
                !sidebarToggle.contains(e.target)) {
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
        updateBundleStatusChart({
            'Pending': 3,
            'In Progress': 5,
            'Completed': 6
        });
        updateDepartmentChart({
            'Cutting': 8,
            'Sewing': 12,
            'Finishing': 6,
            'Quality': 4,
            'Packing': 3
        });
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
                activityFeed.innerHTML = `
                    <div class="activity-item">
                        <span class="activity-text">No recent activity</span>
                        <span class="activity-time">-</span>
                    </div>
                `;
            } else {
                activityFeed.innerHTML = activities.map(activity => `
                    <div class="activity-item">
                        <span class="activity-text">${activity.type}: ${activity.description}</span>
                        <span class="activity-time">${formatTime(activity.created_at)}</span>
                    </div>
                `).join('');
            }
        }
    } catch (error) {
        console.error('Error loading recent activity:', error);
    }
}

// Workers functions
async function loadWorkers() {
    const searchTerm = document.getElementById('workerSearch')?.value || '';
    const department = document.getElementById('departmentFilter')?.value || '';
    const status = document.getElementById('statusFilter')?.value || '';
    
    try {
        const params = new URLSearchParams({ search: searchTerm, department, status });
        const response = await fetch(`/api/workers?${params}`);
        const workers = await response.json();
        
        updateWorkersTable(workers);
    } catch (error) {
        console.error('Error loading workers:', error);
        updateWorkersTable([]);
    }
}

function updateWorkersTable(workers) {
    const tbody = document.getElementById('workersTable');
    if (!tbody) return;

    if (workers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No workers found</td></tr>';
        return;
    }

    tbody.innerHTML = workers.map(worker => `
        <tr>
            <td>${worker.name}</td>
            <td><code>${worker.token_id}</code></td>
            <td><span class="department-tag">${worker.department}</span></td>
            <td>${worker.line || 'N/A'}</td>
            <td><span class="status-badge status-${worker.status.toLowerCase()}">${worker.status}</span></td>
            <td>
                ${worker.qr_code ? `
                    <button class="btn btn--outline btn-sm" onclick="showQRCode('${worker.token_id}', '${worker.qr_code}')">
                        View QR
                    </button>
                ` : 'N/A'}
            </td>
            <td>
                <button class="btn btn--outline btn-sm" onclick="editWorker(${worker.id})">
                    Edit
                </button>
            </td>
        </tr>
    `).join('');
}

function searchWorkers() {
    loadWorkers();
}

// Operations functions
async function loadOperations() {
    const searchTerm = document.getElementById('operationSearch')?.value || '';
    
    try {
        const params = new URLSearchParams({ search: searchTerm });
        const response = await fetch(`/api/operations?${params}`);
        const operations = await response.json();
        
        updateOperationsTable(operations);
    } catch (error) {
        console.error('Error loading operations:', error);
        updateOperationsTable([]);
    }
}

function updateOperationsTable(operations) {
    const tbody = document.getElementById('operationsTable');
    if (!tbody) return;

    if (operations.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No operations found</td></tr>';
        return;
    }

    tbody.innerHTML = operations.map(op => `
        <tr>
            <td>${op.seq_no || '-'}</td>
            <td><code>${op.op_no}</code></td>
            <td>${op.description}</td>
            <td>${op.machine || 'N/A'}</td>
            <td><span class="department-tag">${op.department}</span></td>
            <td>${op.std_min ? op.std_min + ' min' : 'N/A'}</td>
            <td>${op.piece_rate ? '₹' + op.piece_rate : 'N/A'}</td>
        </tr>
    `).join('');
}

function searchOperations() {
    loadOperations();
}

// Bundles functions
async function loadBundles() {
    try {
        const response = await fetch('/api/bundles');
        const bundles = await response.json();
        
        updateBundlesGrid(bundles);
    } catch (error) {
        console.error('Error loading bundles:', error);
        updateBundlesGrid([]);
    }
}

function updateBundlesGrid(bundles) {
    const grid = document.getElementById('bundlesGrid');
    if (!grid) return;

    if (bundles.length === 0) {
        grid.innerHTML = '<div class="loading-card">No bundles found</div>';
        return;
    }

    grid.innerHTML = bundles.map(bundle => `
        <div class="bundle-card">
            <div class="bundle-header">
                <div class="bundle-id">${bundle.bundle_no}</div>
                <span class="status-badge status-${bundle.status.toLowerCase().replace(' ', '-')}">${bundle.status}</span>
            </div>
            <div class="bundle-details">
                <div class="bundle-detail">
                    <span>Style:</span>
                    <strong>${bundle.style}</strong>
                </div>
                <div class="bundle-detail">
                    <span>Color:</span>
                    <strong>${bundle.color}</strong>
                </div>
                <div class="bundle-detail">
                    <span>Size:</span>
                    <strong>${bundle.size}</strong>
                </div>
                <div class="bundle-detail">
                    <span>Quantity:</span>
                    <strong>${bundle.quantity}</strong>
                </div>
                <div class="bundle-detail">
                    <span>Created:</span>
                    <strong>${formatDate(bundle.created_at)}</strong>
                </div>
            </div>
        </div>
    `).join('');
}

// Production Order functions
async function loadProductionOrder() {
    try {
        const response = await fetch('/api/production-order');
        const order = await response.json();
        
        updateProductionOrder(order);
    } catch (error) {
        console.error('Error loading production order:', error);
        updateProductionOrder({});
    }
}

function updateProductionOrder(order) {
    document.getElementById('orderNo').textContent = order.order_no || 'No order found';
    document.getElementById('orderStyle').textContent = order.style || 'N/A';
    document.getElementById('orderQuantity').textContent = order.quantity ? order.quantity.toLocaleString() : 'N/A';
    document.getElementById('orderBuyer').textContent = order.buyer || 'N/A';
}

// File Upload functions
function setupFileUploads() {
    // Excel file upload
    const excelFile = document.getElementById('excelFile');
    if (excelFile) {
        excelFile.addEventListener('change', (e) => handleFileUpload(e, 'excel'));
    }

    // PDF file upload
    const pdfFile = document.getElementById('pdfFile');
    if (pdfFile) {
        pdfFile.addEventListener('change', (e) => handleFileUpload(e, 'pdf'));
    }

    // Drag and drop
    document.querySelectorAll('.upload-area').forEach(area => {
        area.addEventListener('dragover', handleDragOver);
        area.addEventListener('drop', handleDrop);
        area.addEventListener('dragleave', handleDragLeave);
    });
}

function handleDragOver(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = '#3b82f6';
    e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.05)';
}

function handleDragLeave(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = '';
    e.currentTarget.style.backgroundColor = '';
}

function handleDrop(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = '';
    e.currentTarget.style.backgroundColor = '';
    
    const files = e.dataTransfer.files;
    const uploadType = e.currentTarget.dataset.uploadType;
    
    if (files.length > 0) {
        handleFileUpload({ target: { files } }, uploadType);
    }
}

async function handleFileUpload(event, type) {
    const file = event.target.files[0];
    if (!file) return;

    const statusElement = document.getElementById(type + 'Status');
    statusElement.innerHTML = 'Uploading...';
    statusElement.className = 'upload-status';

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
            statusElement.innerHTML = `✅ ${result.filename} uploaded successfully!`;
            statusElement.className = 'upload-status upload-success';
        } else {
            throw new Error(result.error || 'Upload failed');
        }
    } catch (error) {
        statusElement.innerHTML = `❌ Error: ${error.message}`;
        statusElement.className = 'upload-status upload-error';
    }
}

// Scanner functions
function setupScannerControls() {
    const startScan = document.getElementById('startScan');
    const stopScan = document.getElementById('stopScan');
    const resetScan = document.getElementById('resetScan');

    if (startScan) startScan.addEventListener('click', startScanning);
    if (stopScan) stopScan.addEventListener('click', stopScanning);
    if (resetScan) resetScan.addEventListener('click', resetScanner);
}

function startScanning() {
    if (isScanning) return;

    isScanning = true;
    document.getElementById('startScan').disabled = true;
    document.getElementById('stopScan').disabled = false;
    document.getElementById('scannerStatus').textContent = 'Scanning...';

    // Simulate scanning with random codes
    scanInterval = setInterval(() => {
        const randomCode = generateRandomCode();
        displayScanResult(randomCode);
        saveScan(randomCode);
    }, 3000);
}

function stopScanning() {
    if (!isScanning) return;

    isScanning = false;
    clearInterval(scanInterval);
    
    document.getElementById('startScan').disabled = false;
    document.getElementById('stopScan').disabled = true;
    document.getElementById('scannerStatus').textContent = 'Stopped';
}

function resetScanner() {
    stopScanning();
    document.getElementById('scannerStatus').textContent = 'Ready to Scan';
    document.getElementById('scanResult').textContent = '';
    loadRecentScans();
}

function generateRandomCode() {
    const prefixes = ['W', 'B', 'O'];
    const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
    const number = Math.floor(Math.random() * 999) + 1;
    return prefix + number.toString().padStart(3, '0');
}

function displayScanResult(code) {
    const resultElement = document.getElementById('scanResult');
    if (resultElement) {
        resultElement.textContent = code;
        resultElement.style.animation = 'slideUp 0.5s ease-in-out';
    }
}

async function saveScan(code) {
    try {
        await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        loadRecentScans();
    } catch (error) {
        console.error('Error saving scan:', error);
    }
}

async function loadRecentScans() {
    try {
        const response = await fetch('/api/scans');
        const scans = await response.json();
        
        const scansList = document.getElementById('recentScans');
        if (scansList) {
            if (scans.length === 0) {
                scansList.innerHTML = '<div class="scan-item">No recent scans</div>';
            } else {
                scansList.innerHTML = scans.slice(0, 10).map(scan => `
                    <div class="scan-item">
                        <span class="scan-code">${scan.code}</span>
                        <span class="scan-time">${formatTime(scan.created_at)}</span>
                    </div>
                `).join('');
            }
        }
    } catch (error) {
        console.error('Error loading recent scans:', error);
    }
}

// Reports functions
function generateReport(type) {
    // Simulate report generation
    alert(`Generating ${type} report... This feature will be implemented soon.`);
}

// Utility functions
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function formatTime(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    const now = new Date();
    const diffInMinutes = Math.floor((now - date) / (1000 * 60));
    
    if (diffInMinutes < 1) return 'Just now';
    if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
    
    const diffInHours = Math.floor(diffInMinutes / 60);
    if (diffInHours < 24) return `${diffInHours}h ago`;
    
    const diffInDays = Math.floor(diffInHours / 24);
    return `${diffInDays}d ago`;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Auto refresh
function startAutoRefresh() {
    // Refresh dashboard data every 30 seconds
    refreshInterval = setInterval(() => {
        if (currentSection === 'dashboard') {
            loadDashboardStats();
            loadRecentActivity();
        }
    }, 30000);
}

function refreshDashboard() {
    const button = document.getElementById('refreshBtn');
    if (button) {
        button.disabled = true;
        button.textContent = 'Refreshing...';
        
        loadDashboard().then(() => {
            button.disabled = false;
            button.textContent = 'Refresh';
            updateLastUpdated();
        });
    }
}

function updateLastUpdated() {
    const element = document.getElementById('lastUpdated');
    if (element) {
        element.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
    }
}

// Modal functions (for future use)
function showQRCode(tokenId, qrCode) {
    // Create a simple modal to show QR code
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;
    
    modal.innerHTML = `
        <div style="background: #1a1d2e; padding: 2rem; border-radius: 12px; text-align: center; max-width: 400px;">
            <h3 style="color: white; margin-bottom: 1rem;">QR Code - ${tokenId}</h3>
            <img src="${qrCode}" alt="QR Code" style="max-width: 100%; border-radius: 8px;">
            <br><br>
            <button onclick="this.parentElement.parentElement.remove()" 
                    style="background: #3b82f6; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 8px; cursor: pointer;">
                Close
            </button>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Close on background click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

function editWorker(workerId) {
    alert(`Edit worker functionality will be implemented soon. Worker ID: ${workerId}`);
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    clearInterval(refreshInterval);
    clearInterval(scanInterval);
});
