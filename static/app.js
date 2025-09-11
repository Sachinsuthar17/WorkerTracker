// Production Scanner Dashboard JavaScript

// Application data - from provided JSON
const appData = {
    "workers": [
        {"id": 1, "name": "John Smith", "token_id": "JS001", "department": "Cutting", "status": "active", "created_at": "2024-01-15"},
        {"id": 2, "name": "Sarah Johnson", "token_id": "SJ002", "department": "Sewing", "status": "active", "created_at": "2024-01-16"},
        {"id": 3, "name": "Mike Chen", "token_id": "MC003", "department": "Quality Control", "status": "active", "created_at": "2024-01-17"},
        {"id": 4, "name": "Lisa Davis", "token_id": "LD004", "department": "Packing", "status": "active", "created_at": "2024-01-18"}
    ],
    "operations": [
        {"id": 1, "name": "Cutting", "operation_code": "CUT", "description": "Fabric cutting operation"},
        {"id": 2, "name": "Sewing", "operation_code": "SEW", "description": "Sewing operation"},
        {"id": 3, "name": "Quality Check", "operation_code": "QC", "description": "Quality inspection"},
        {"id": 4, "name": "Packing", "operation_code": "PACK", "description": "Final packing"}
    ],
    "scans": [
        {"id": 1, "worker_name": "John Smith", "department": "Cutting", "barcode": "OP10-BATCH001", "timestamp": "2024-01-20 09:15:30"},
        {"id": 2, "worker_name": "Sarah Johnson", "department": "Sewing", "barcode": "OP20-BATCH002", "timestamp": "2024-01-20 09:45:22"},
        {"id": 3, "worker_name": "Mike Chen", "department": "Quality Control", "barcode": "OP30-BATCH003", "timestamp": "2024-01-20 10:12:45"},
        {"id": 4, "worker_name": "Lisa Davis", "department": "Packing", "barcode": "OP40-BATCH004", "timestamp": "2024-01-20 10:30:15"},
        {"id": 5, "worker_name": "John Smith", "department": "Cutting", "barcode": "OP10-BATCH005", "timestamp": "2024-01-20 11:20:30"}
    ],
    "production_logs": [
        {"id": 1, "worker_name": "John Smith", "operation_name": "Cutting", "quantity": 25, "timestamp": "2024-01-20 09:00:00", "status": "completed"},
        {"id": 2, "worker_name": "Sarah Johnson", "operation_name": "Sewing", "quantity": 20, "timestamp": "2024-01-20 10:00:00", "status": "completed"},
        {"id": 3, "worker_name": "Mike Chen", "operation_name": "Quality Check", "quantity": 18, "timestamp": "2024-01-20 11:00:00", "status": "completed"},
        {"id": 4, "worker_name": "Lisa Davis", "operation_name": "Packing", "quantity": 15, "timestamp": "2024-01-20 12:00:00", "status": "completed"}
    ],
    "stats": {
        "pieces_today": 78,
        "workers_today": 4,
        "earnings_today": 156.00,
        "total_workers": 4,
        "rate_per_piece": 2.00,
        "active_worker": "John Smith"
    },
    "settings": {
        "brand": "Production Scanner",
        "device_secret": "u38fh39f...",
        "rate_per_piece": 2.00,
        "database": "SQLite (production.db)",
        "api_endpoints": [
            {"name": "Scan Endpoint", "path": "POST /scan"},
            {"name": "Stats API", "path": "GET /api/stats"},
            {"name": "Activities API", "path": "GET /api/activities"}
        ]
    }
};

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM Content Loaded - Initializing application...');
    
    initializeNavigation();
    initializeMobileMenu();
    initializeForms();
    populateAllData();
    setupAutoRefresh();
    
    console.log('Application initialized successfully');
});

// Navigation functionality - Fixed
function initializeNavigation() {
    const menuItems = document.querySelectorAll('.menu-item');
    const contentSections = document.querySelectorAll('.content-section');
    
    console.log('Found menu items:', menuItems.length);
    console.log('Found content sections:', contentSections.length);
    
    menuItems.forEach((item, index) => {
        const menuLink = item.querySelector('.menu-link');
        if (menuLink) {
            menuLink.addEventListener('click', function(e) {
                e.preventDefault();
                const sectionId = item.getAttribute('data-section');
                console.log(`Navigating to section: ${sectionId}`);
                
                showSection(sectionId);
                updateActiveMenuItem(item);
                
                // Close mobile menu on navigation
                const sidebar = document.getElementById('sidebar');
                if (window.innerWidth <= 768 && sidebar) {
                    sidebar.classList.remove('open');
                }
            });
        }
    });
}

function showSection(sectionId) {
    const contentSections = document.querySelectorAll('.content-section');
    
    // Hide all sections
    contentSections.forEach(section => {
        section.classList.remove('active');
        section.style.display = 'none';
    });
    
    // Show target section
    const targetSection = document.getElementById(sectionId);
    if (targetSection) {
        targetSection.classList.add('active');
        targetSection.style.display = 'block';
        console.log(`Showing section: ${sectionId}`);
        
        // Refresh data for the current section
        refreshSectionData(sectionId);
    } else {
        console.error(`Section not found: ${sectionId}`);
    }
}

function updateActiveMenuItem(activeItem) {
    const menuItems = document.querySelectorAll('.menu-item');
    menuItems.forEach(item => {
        item.classList.remove('active');
    });
    activeItem.classList.add('active');
}

// Mobile menu functionality
function initializeMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    
    if (mobileMenuToggle && sidebar) {
        mobileMenuToggle.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
        
        // Close sidebar when clicking outside
        document.addEventListener('click', function(e) {
            if (window.innerWidth <= 768 && 
                !sidebar.contains(e.target) && 
                !mobileMenuToggle.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });
    }
}

// Form initialization - Fixed
function initializeForms() {
    console.log('Initializing forms...');
    
    // Add Worker Form
    const addWorkerForm = document.getElementById('addWorkerForm');
    if (addWorkerForm) {
        addWorkerForm.addEventListener('submit', function(e) {
            e.preventDefault();
            console.log('Worker form submitted');
            handleAddWorker(e);
        });
        console.log('Worker form initialized');
    }
    
    // Add Operation Form
    const addOperationForm = document.getElementById('addOperationForm');
    if (addOperationForm) {
        addOperationForm.addEventListener('submit', function(e) {
            e.preventDefault();
            console.log('Operation form submitted');
            handleAddOperation(e);
        });
        console.log('Operation form initialized');
    }
    
    // Add Production Form
    const addProductionForm = document.getElementById('addProductionForm');
    if (addProductionForm) {
        addProductionForm.addEventListener('submit', function(e) {
            e.preventDefault();
            console.log('Production form submitted');
            handleAddProduction(e);
        });
        console.log('Production form initialized');
    }
}

// Populate all data on page load
function populateAllData() {
    console.log('Populating all data...');
    populateDashboardStats();
    populateActivitiesTable();
    populateActiveWorkerInfo();
    populateWorkersTable();
    populateOperationsTable();
    populateProductionTable();
    populateProductionDropdowns();
    populateReportsStats();
    console.log('All data populated');
}

// Dashboard functions
function populateDashboardStats() {
    const stats = appData.stats;
    const piecesToday = document.getElementById('piecesToday');
    const workersActive = document.getElementById('workersActive');
    const earningsToday = document.getElementById('earningsToday');
    const totalWorkers = document.getElementById('totalWorkers');
    
    if (piecesToday) piecesToday.textContent = stats.pieces_today;
    if (workersActive) workersActive.textContent = stats.workers_today;
    if (earningsToday) earningsToday.textContent = `$${stats.earnings_today.toFixed(2)}`;
    if (totalWorkers) totalWorkers.textContent = stats.total_workers;
}

function populateActivitiesTable() {
    const tbody = document.getElementById('activitiesTable');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    // Show recent scans (last 5)
    const recentScans = appData.scans.slice(-5).reverse();
    
    recentScans.forEach(scan => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${scan.worker_name}</td>
            <td>${scan.department}</td>
            <td><code>${scan.barcode}</code></td>
            <td>${formatTimestamp(scan.timestamp)}</td>
        `;
        tbody.appendChild(row);
    });
}

function populateActiveWorkerInfo() {
    const activeWorkerInfo = document.getElementById('activeWorkerInfo');
    if (!activeWorkerInfo) return;
    
    const activeWorkerName = appData.stats.active_worker;
    const activeWorker = appData.workers.find(w => w.name === activeWorkerName);
    
    if (activeWorker) {
        activeWorkerInfo.innerHTML = `
            <div class="worker-avatar">
                <i class="fas fa-user"></i>
            </div>
            <div class="worker-details">
                <div class="worker-name">${activeWorker.name}</div>
                <div class="worker-department">${activeWorker.department} Department</div>
            </div>
        `;
    }
}

// Workers functions - Fixed
function populateWorkersTable() {
    const tbody = document.getElementById('workersTable');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    appData.workers.forEach(worker => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${worker.name}</td>
            <td><code>${worker.token_id}</code></td>
            <td>${worker.department}</td>
            <td><span class="status status--active">${worker.status}</span></td>
            <td>${formatDate(worker.created_at)}</td>
            <td>
                <button class="btn action-btn action-btn--qr" onclick="generateQR('${worker.token_id}')">
                    <i class="fas fa-qrcode"></i> QR
                </button>
                <button class="btn action-btn action-btn--delete" onclick="deleteWorker(${worker.id})">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function handleAddWorker(e) {
    console.log('Handling add worker...');
    
    const workerName = document.getElementById('workerName').value.trim();
    const workerTokenId = document.getElementById('workerTokenId').value.trim();
    const workerDepartment = document.getElementById('workerDepartment').value;
    
    console.log('Worker data:', {workerName, workerTokenId, workerDepartment});
    
    if (!workerName || !workerTokenId || !workerDepartment) {
        alert('Please fill in all required fields');
        return;
    }
    
    const newWorker = {
        id: appData.workers.length + 1,
        name: workerName,
        token_id: workerTokenId,
        department: workerDepartment,
        status: 'active',
        created_at: new Date().toISOString().split('T')[0]
    };
    
    // Add to data
    appData.workers.push(newWorker);
    console.log('Worker added:', newWorker);
    
    // Refresh table and dropdowns
    populateWorkersTable();
    populateProductionDropdowns();
    
    // Reset form
    e.target.reset();
    
    // Show success message
    showSuccessMessage('Worker added successfully!');
}

function deleteWorker(workerId) {
    if (confirm('Are you sure you want to delete this worker?')) {
        appData.workers = appData.workers.filter(w => w.id !== workerId);
        populateWorkersTable();
        populateProductionDropdowns();
        showSuccessMessage('Worker deleted successfully!');
    }
}

function generateQR(tokenId) {
    alert(`QR Code generated for Token ID: ${tokenId}`);
}

// Operations functions - Fixed
function populateOperationsTable() {
    const tbody = document.getElementById('operationsTable');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    appData.operations.forEach(operation => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${operation.name}</td>
            <td><code>${operation.operation_code}</code></td>
            <td>${operation.description}</td>
            <td>
                <button class="btn action-btn action-btn--delete" onclick="deleteOperation(${operation.id})">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function handleAddOperation(e) {
    console.log('Handling add operation...');
    
    const operationName = document.getElementById('operationName').value.trim();
    const operationCode = document.getElementById('operationCode').value.trim();
    const operationDescription = document.getElementById('operationDescription').value.trim();
    
    if (!operationName || !operationCode) {
        alert('Please fill in all required fields');
        return;
    }
    
    const newOperation = {
        id: appData.operations.length + 1,
        name: operationName,
        operation_code: operationCode,
        description: operationDescription || ''
    };
    
    // Add to data
    appData.operations.push(newOperation);
    console.log('Operation added:', newOperation);
    
    // Refresh table and dropdowns
    populateOperationsTable();
    populateProductionDropdowns();
    
    // Reset form
    e.target.reset();
    
    // Show success message
    showSuccessMessage('Operation added successfully!');
}

function deleteOperation(operationId) {
    if (confirm('Are you sure you want to delete this operation?')) {
        appData.operations = appData.operations.filter(o => o.id !== operationId);
        populateOperationsTable();
        populateProductionDropdowns();
        showSuccessMessage('Operation deleted successfully!');
    }
}

// Production functions - Fixed with better validation and dropdown handling
function populateProductionTable() {
    const tbody = document.getElementById('productionTable');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    appData.production_logs.forEach(log => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>#${log.id}</td>
            <td>${log.worker_name}</td>
            <td>${log.operation_name}</td>
            <td>${log.quantity}</td>
            <td>${formatTimestamp(log.timestamp)}</td>
            <td><span class="status status--completed">${log.status}</span></td>
        `;
        tbody.appendChild(row);
    });
}

function populateProductionDropdowns() {
    console.log('Populating production dropdowns...');
    
    // Populate worker dropdown
    const workerSelect = document.getElementById('productionWorker');
    if (workerSelect) {
        workerSelect.innerHTML = '<option value="">Select Worker</option>';
        appData.workers.forEach(worker => {
            const option = document.createElement('option');
            option.value = worker.name;
            option.textContent = `${worker.name} (${worker.department})`;
            workerSelect.appendChild(option);
        });
        console.log('Worker dropdown populated with', appData.workers.length, 'workers');
    }
    
    // Populate operation dropdown
    const operationSelect = document.getElementById('productionOperation');
    if (operationSelect) {
        operationSelect.innerHTML = '<option value="">Select Operation</option>';
        appData.operations.forEach(operation => {
            const option = document.createElement('option');
            option.value = operation.name;
            option.textContent = `${operation.name} (${operation.operation_code})`;
            operationSelect.appendChild(option);
        });
        console.log('Operation dropdown populated with', appData.operations.length, 'operations');
    }
}

function handleAddProduction(e) {
    console.log('Handling add production...');
    
    const workerSelect = document.getElementById('productionWorker');
    const operationSelect = document.getElementById('productionOperation');
    const quantityInput = document.getElementById('productionQuantity');
    
    const productionWorker = workerSelect ? workerSelect.value : '';
    const productionOperation = operationSelect ? operationSelect.value : '';
    const productionQuantity = quantityInput ? quantityInput.value : '';
    
    console.log('Production form values:', {
        worker: productionWorker,
        operation: productionOperation,
        quantity: productionQuantity
    });
    
    // Validation
    if (!productionWorker) {
        alert('Please select a worker');
        if (workerSelect) workerSelect.focus();
        return;
    }
    
    if (!productionOperation) {
        alert('Please select an operation');
        if (operationSelect) operationSelect.focus();
        return;
    }
    
    if (!productionQuantity) {
        alert('Please enter a quantity');
        if (quantityInput) quantityInput.focus();
        return;
    }
    
    const quantity = parseInt(productionQuantity);
    if (isNaN(quantity) || quantity <= 0) {
        alert('Please enter a valid quantity (greater than 0)');
        if (quantityInput) quantityInput.focus();
        return;
    }
    
    // Create new production log entry
    const newProduction = {
        id: appData.production_logs.length + 1,
        worker_name: productionWorker,
        operation_name: productionOperation,
        quantity: quantity,
        timestamp: new Date().toISOString().replace('T', ' ').split('.')[0],
        status: 'completed'
    };
    
    // Add to data
    appData.production_logs.push(newProduction);
    console.log('Production logged:', newProduction);
    
    // Update stats
    appData.stats.pieces_today += quantity;
    appData.stats.earnings_today += (quantity * appData.stats.rate_per_piece);
    
    // Refresh tables and stats
    populateProductionTable();
    populateDashboardStats();
    populateReportsStats();
    
    // Reset form
    if (workerSelect) workerSelect.value = '';
    if (operationSelect) operationSelect.value = '';
    if (quantityInput) quantityInput.value = '';
    
    // Show success message
    showSuccessMessage(`Production logged successfully! ${quantity} units recorded for ${productionWorker}`);
}

// Reports functions
function populateReportsStats() {
    const scansToday = document.getElementById('scansToday');
    const productionEntries = document.getElementById('productionEntries');
    const totalQuantity = document.getElementById('totalQuantity');
    
    if (scansToday) scansToday.textContent = appData.scans.length;
    if (productionEntries) productionEntries.textContent = appData.production_logs.length;
    
    const totalQty = appData.production_logs.reduce((sum, log) => sum + log.quantity, 0);
    if (totalQuantity) totalQuantity.textContent = totalQty;
}

function exportData(type) {
    const messages = {
        'scans': 'Scans data exported successfully!',
        'production': 'Production data exported successfully!',
        'workers': 'Workers data exported successfully!'
    };
    
    showSuccessMessage(messages[type] || 'Data exported successfully!');
}

// Utility functions
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: '2-digit'
    });
}

function showSuccessMessage(message) {
    // Create success message element if it doesn't exist
    let successDiv = document.querySelector('.success-feedback');
    if (!successDiv) {
        successDiv = document.createElement('div');
        successDiv.className = 'success-feedback';
        successDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: #10b981;
            padding: 12px 20px;
            border-radius: 8px;
            z-index: 10000;
            display: none;
            backdrop-filter: blur(10px);
            max-width: 300px;
            font-size: 14px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        `;
        document.body.appendChild(successDiv);
    }
    
    successDiv.textContent = message;
    successDiv.style.display = 'block';
    
    // Auto-hide after 3 seconds
    setTimeout(() => {
        successDiv.style.display = 'none';
    }, 3000);
}

// Auto-refresh functionality
function setupAutoRefresh() {
    setInterval(() => {
        const currentSection = document.querySelector('.content-section.active');
        if (currentSection && currentSection.id === 'dashboard') {
            refreshActivities();
        }
    }, 30000);
}

function refreshActivities() {
    const workers = ['John Smith', 'Sarah Johnson', 'Mike Chen', 'Lisa Davis'];
    const departments = ['Cutting', 'Sewing', 'Quality Control', 'Packing'];
    const barcodes = ['OP10-BATCH006', 'OP20-BATCH007', 'OP30-BATCH008', 'OP40-BATCH009'];
    
    const randomWorker = workers[Math.floor(Math.random() * workers.length)];
    const randomDepartment = departments[Math.floor(Math.random() * departments.length)];
    const randomBarcode = barcodes[Math.floor(Math.random() * barcodes.length)];
    
    const newScan = {
        id: appData.scans.length + 1,
        worker_name: randomWorker,
        department: randomDepartment,
        barcode: randomBarcode,
        timestamp: new Date().toISOString().replace('T', ' ').split('.')[0]
    };
    
    appData.scans.push(newScan);
    populateActivitiesTable();
}

function refreshSectionData(sectionId) {
    switch(sectionId) {
        case 'dashboard':
            populateDashboardStats();
            populateActivitiesTable();
            populateActiveWorkerInfo();
            break;
        case 'workers':
            populateWorkersTable();
            break;
        case 'operations':
            populateOperationsTable();
            break;
        case 'production':
            populateProductionTable();
            populateProductionDropdowns();
            break;
        case 'reports':
            populateReportsStats();
            break;
    }
}

// Global functions for inline event handlers
window.deleteWorker = deleteWorker;
window.deleteOperation = deleteOperation;
window.generateQR = generateQR;
window.exportData = exportData;
window.refreshActivities = refreshActivities;

// Handle window resize
window.addEventListener('resize', function() {
    const sidebar = document.getElementById('sidebar');
    if (window.innerWidth > 768 && sidebar) {
        sidebar.classList.remove('open');
    }
});

// Keyboard navigation
document.addEventListener('keydown', function(e) {
    const sidebar = document.getElementById('sidebar');
    if (e.key === 'Escape' && sidebar) {
        sidebar.classList.remove('open');
    }
});

console.log('Production Scanner Dashboard script loaded successfully');