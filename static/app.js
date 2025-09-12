// Production Management System - JavaScript

document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Initialize navigation
    updateActiveNavItem();

    // Initialize file upload areas
    initializeFileUploads();

    // Initialize scanner if on scanner page
    if (document.getElementById('scanArea')) {
        initializeScanner();
    }
}

function updateActiveNavItem() {
    const currentPath = window.location.pathname;
    const navItems = document.querySelectorAll('.nav-item');

    navItems.forEach(item => {
        item.classList.remove('active');
        const href = item.getAttribute('href');
        if (href && (currentPath === href || currentPath.includes(href.substring(1)))) {
            item.classList.add('active');
        }
    });
}

function initializeFileUploads() {
    const uploadAreas = document.querySelectorAll('.upload-area');

    uploadAreas.forEach(area => {
        area.addEventListener('dragover', handleDragOver);
        area.addEventListener('dragleave', handleDragLeave);
        area.addEventListener('drop', handleDrop);
    });
}

function handleDragOver(e) {
    e.preventDefault();
    this.style.borderColor = '#00bcd4';
    this.style.background = 'rgba(0, 188, 212, 0.1)';
}

function handleDragLeave(e) {
    e.preventDefault();
    this.style.borderColor = '#2d3748';
    this.style.background = 'transparent';
}

function handleDrop(e) {
    e.preventDefault();
    this.style.borderColor = '#2d3748';
    this.style.background = 'transparent';

    const files = e.dataTransfer.files;
    if (files.length > 0) {
        const fileInput = this.querySelector('input[type="file"]');
        fileInput.files = files;

        const filenameDiv = this.querySelector('.filename');
        if (filenameDiv) {
            filenameDiv.textContent = `Selected: ${files[0].name}`;
            filenameDiv.style.color = '#00bcd4';
        }
    }
}

function initializeScanner() {
    // Scanner functionality is handled in the template
}

// Utility functions
function showAlert(message, type = 'info') {
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.textContent = message;

    const content = document.querySelector('.content');
    content.insertBefore(alert, content.firstChild);

    setTimeout(() => {
        alert.remove();
    }, 5000);
}

function updateFileName(input, targetId) {
    const target = document.getElementById(targetId);
    if (input.files.length > 0) {
        target.textContent = `Selected: ${input.files[0].name}`;
        target.style.color = '#00bcd4';
    }
}

// ESP32 Scanner functions (from template)
function simulateScan() {
    const scanArea = document.getElementById('scanArea');
    const workers = [
        {name: 'Vikram Yadav (VY005)', action: 'LOGIN'},
        {name: 'Kavita Patel (KP006)', action: 'LOGOUT'},
        {name: 'Ravi Gupta (RG007)', action: 'LOGIN'}
    ];

    const worker = workers[Math.floor(Math.random() * workers.length)];
    const now = new Date().toLocaleTimeString();

    scanArea.textContent = `Scanning ${worker.name}...`;

    setTimeout(() => {
        scanArea.textContent = 'Ready to scan...';
        addLogEntry(worker.name, worker.action, now);
    }, 1500);
}

function addLogEntry(workerName, action, time) {
    const logBody = document.getElementById('scanLogBody');
    const logItem = document.createElement('div');
    logItem.className = 'log-item';

    logItem.innerHTML = `
        <div class="worker-info">
            <div class="worker-name">${workerName}</div>
            <div class="worker-time">${time}</div>
        </div>
        <div class="status-badge status-${action.toLowerCase()}">${action}</div>
    `;

    logBody.insertBefore(logItem, logBody.firstChild);

    // Keep only last 10 entries
    while (logBody.children.length > 10) {
        logBody.removeChild(logBody.lastChild);
    }
}

function resetScanner() {
    const scanArea = document.getElementById('scanArea');
    if (scanArea) {
        scanArea.textContent = 'Ready to scan...';
    }
}
