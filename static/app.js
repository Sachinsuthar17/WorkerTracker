// Production Management System - JavaScript

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    initializeNavigation();
    initializeMobileMenu();
    initializeForms();
    setupFileUploadHandlers();
});

// Navigation Management
function initializeNavigation() {
    const sidebar = document.getElementById('sidebar');
    const menuItems = document.querySelectorAll('.menu-item');

    // Highlight current page
    const currentPath = window.location.pathname;
    menuItems.forEach(item => {
        const href = item.getAttribute('href');
        if (href && currentPath.includes(href.replace('/', ''))) {
            item.classList.add('active');
        }
    });
}

// Mobile Menu Management
function initializeMobileMenu() {
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebar = document.getElementById('sidebar');
    const mobileToggle = document.getElementById('mobileToggle');

    if (mobileMenuBtn && sidebar) {
        mobileMenuBtn.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
    }

    if (mobileToggle && sidebar) {
        mobileToggle.addEventListener('click', function() {
            sidebar.classList.remove('open');
        });
    }

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 768 && sidebar && sidebar.classList.contains('open')) {
            if (!sidebar.contains(e.target) && !mobileMenuBtn.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        }
    });

    // Handle window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768 && sidebar) {
            sidebar.classList.remove('open');
        }
    });
}

// Form Management
function initializeForms() {
    const forms = document.querySelectorAll('form');

    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                showButtonLoading(submitBtn);
            }
        });
    });
}

function showButtonLoading(button) {
    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

    // Store original text for restoration if needed
    button.dataset.originalText = originalText;
}

// File Upload Management
function setupFileUploadHandlers() {
    const uploadAreas = document.querySelectorAll('.file-upload-area');

    uploadAreas.forEach(area => {
        const fileInput = area.querySelector('.file-input');
        const uploadText = area.querySelector('.file-upload-text');

        if (!fileInput) return;

        // Click to select file
        area.addEventListener('click', function() {
            fileInput.click();
        });

        // File selection change
        fileInput.addEventListener('change', function(e) {
            const files = e.target.files;
            if (files.length > 0) {
                updateUploadAreaText(uploadText, files[0].name, true);
            }
        });

        // Drag and drop
        area.addEventListener('dragover', function(e) {
            e.preventDefault();
            area.classList.add('dragover');
        });

        area.addEventListener('dragleave', function(e) {
            e.preventDefault();
            area.classList.remove('dragover');
        });

        area.addEventListener('drop', function(e) {
            e.preventDefault();
            area.classList.remove('dragover');

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                updateUploadAreaText(uploadText, files[0].name, true);
            }
        });
    });
}

function updateUploadAreaText(textElement, fileName, isSelected) {
    if (isSelected) {
        textElement.innerHTML = `<strong>Selected:</strong> ${fileName}`;
        textElement.parentNode.classList.add('file-selected');
    } else {
        textElement.innerHTML = '<strong>Choose File</strong> or drag and drop';
        textElement.parentNode.classList.remove('file-selected');
    }
}

// Auto-refresh functionality for dashboard
if (window.location.pathname === '/' || window.location.pathname.includes('dashboard')) {
    setInterval(function() {
        if (document.visibilityState === 'visible') {
            fetch('/api/dashboard_stats')
                .then(response => response.json())
                .then(data => {
                    updateDashboardStats(data);
                })
                .catch(error => console.error('Error refreshing data:', error));
        }
    }, 30000); // Refresh every 30 seconds
}

function updateDashboardStats(data) {
    const elements = {
        'totalWorkers': data.total_workers,
        'totalBundles': data.total_bundles,
        'pendingBundles': data.pending_bundles,
        'completedBundles': data.completed_bundles,
        'totalPieces': data.total_pieces,
        'totalEarnings': `₹${data.total_earnings}`
    };

    Object.keys(elements).forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = elements[id];
        }
    });
}

// Search functionality
document.addEventListener('input', function(e) {
    if (e.target.classList.contains('search-input')) {
        const searchTerm = e.target.value.toLowerCase();
        const tableId = e.target.id.replace('search', '') + 'Table';
        const table = document.getElementById(tableId);

        if (table) {
            const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');

            Array.from(rows).forEach(row => {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(searchTerm) ? '' : 'none';
            });
        }
    }
});

// Alert close functionality
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('alert__close')) {
        e.target.parentElement.remove();
    }
});

// Utility functions
function showAlert(message, type = 'info') {
    const alertContainer = document.querySelector('.flash-messages') || createAlertContainer();

    const alert = document.createElement('div');
    alert.className = `alert alert--${type}`;
    alert.innerHTML = `
        ${message}
        <button class="alert__close">&times;</button>
    `;

    alertContainer.appendChild(alert);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (alert.parentNode) {
            alert.remove();
        }
    }, 5000);
}

function createAlertContainer() {
    const container = document.createElement('div');
    container.className = 'flash-messages';

    const mainContent = document.querySelector('.main-content');
    if (mainContent) {
        mainContent.insertBefore(container, mainContent.firstChild);
    }

    return container;
}