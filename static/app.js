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
        console.error('
