// Production Dashboard JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Initialize dashboard if we're on the dashboard page
    if (document.getElementById('statsGrid')) {
        initializeDashboard();
    }

    // Initialize mobile menu
    initializeMobileMenu();
});

let productionChart = null;
let workerChart = null;

// Dashboard initialization
async function initializeDashboard() {
    try {
        await loadStats();
        await loadChartData();
        await loadActivities();
        startLiveUpdates();
        console.log('Dashboard initialized successfully');
    } catch (error) {
        console.error('Error initializing dashboard:', error);
    }
}

// Load and render statistics
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();
        renderStatsCards(stats);
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Render stats cards
function renderStatsCards(stats) {
    const statsGrid = document.getElementById('statsGrid');
    if (!statsGrid) return;

    statsGrid.innerHTML = '';

    const icons = ['chart-line', 'users', 'percentage', 'rupee-sign'];
    const colors = [
        'linear-gradient(135deg, #3b82f6, #1d4ed8)',
        'linear-gradient(135deg, #06b6d4, #0891b2)',
        'linear-gradient(135deg, #f59e0b, #d97706)',
        'linear-gradient(135deg, #10b981, #059669)'
    ];

    Object.values(stats).forEach((stat, index) => {
        const card = document.createElement('div');
        card.className = 'stat-card';

        const changeClass = stat.change >= 0 ? 'positive' : 'negative';
        const changeSymbol = stat.change >= 0 ? '+' : '';

        card.innerHTML = `
            <div class="stat-icon" style="background: ${colors[index]}">
                <i class="fas fa-${icons[index]}"></i>
            </div>
            <div class="stat-content">
                <div class="stat-value">${index === 3 ? '₹' : ''}${formatNumber(stat.value)}${index === 2 ? '%' : ''}</div>
                <div class="stat-label">${stat.label}</div>
                <div class="stat-change ${changeClass}">${changeSymbol}${stat.change}%</div>
            </div>
        `;

        statsGrid.appendChild(card);
    });
}

// Load and render charts
async function loadChartData() {
    try {
        const response = await fetch('/api/chart-data');
        const chartData = await response.json();

        createProductionChart(chartData.dailyProduction);
        createWorkerChart(chartData.workerPerformance);
    } catch (error) {
        console.error('Error loading chart data:', error);
    }
}

// Create production trend chart
function createProductionChart(data) {
    const ctx = document.getElementById('productionChart');
    if (!ctx) return;

    if (productionChart) {
        productionChart.destroy();
    }

    productionChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Daily Production',
                data: data.data,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 3,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#3b82f6',
                pointBorderColor: '#ffffff',
                pointBorderWidth: 2,
                pointRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(30, 41, 59, 0.9)',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: '#374151',
                    borderWidth: 1,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(55, 65, 81, 0.3)' },
                    ticks: { color: '#64748b' }
                },
                y: {
                    grid: { color: 'rgba(55, 65, 81, 0.3)' },
                    ticks: { 
                        color: '#64748b',
                        callback: function(value) {
                            return formatNumber(value);
                        }
                    }
                }
            }
        }
    });
}

// Create worker performance chart
function createWorkerChart(data) {
    const ctx = document.getElementById('workerChart');
    if (!ctx) return;

    if (workerChart) {
        workerChart.destroy();
    }

    const colors = ['#3b82f6', '#06b6d4', '#f59e0b', '#10b981', '#ef4444'];

    workerChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Efficiency %',
                data: data.data,
                backgroundColor: colors,
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(30, 41, 59, 0.9)',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: '#374151',
                    borderWidth: 1,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#64748b' }
                },
                y: {
                    grid: { color: 'rgba(55, 65, 81, 0.3)' },
                    ticks: { 
                        color: '#64748b',
                        callback: function(value) { return value + '%'; }
                    },
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });
}

// Load and render activities
async function loadActivities() {
    try {
        const response = await fetch('/api/activities');
        const activities = await response.json();
        renderActivities(activities);
    } catch (error) {
        console.error('Error loading activities:', error);
    }
}

// Render activities
function renderActivities(activities) {
    const activitiesList = document.getElementById('activitiesList');
    if (!activitiesList) return;

    activitiesList.innerHTML = '';

    activities.forEach(activity => {
        const item = document.createElement('div');
        item.className = 'activity-item';

        const actionColor = activity.action === 'Completed' ? '#10b981' : '#f59e0b';

        item.innerHTML = `
            <div class="activity-info">
                <div class="activity-worker">${activity.worker}</div>
                <div class="activity-action">
                    <span style="color: ${actionColor}">${activity.action}</span> 
                    ${activity.operation}
                </div>
            </div>
            <div class="activity-time">${activity.time}</div>
        `;

        activitiesList.appendChild(item);
    });
}

// Initialize mobile menu
function initializeMobileMenu() {
    const menuToggle = document.getElementById('mobileMenuToggle');
    const sidebar = document.getElementById('sidebar');

    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
        });

        // Close sidebar when clicking outside
        document.addEventListener('click', function(e) {
            if (!sidebar.contains(e.target) && !menuToggle.contains(e.target)) {
                sidebar.classList.remove('show');
            }
        });
    }
}

// Start live updates for dashboard
function startLiveUpdates() {
    setInterval(async function() {
        if (document.getElementById('statsGrid')) {
            await loadStats();
            await loadActivities();
        }
    }, 30000); // Update every 30 seconds
}

// Utility function to format numbers
function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toLocaleString();
}

// Chart button controls
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('chart-btn')) {
        const group = e.target.parentElement;
        group.querySelectorAll('.chart-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        e.target.classList.add('active');
    }
});
