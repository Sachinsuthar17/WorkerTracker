function renderStatsCards(stats) {
    const statsGrid = document.getElementById('statsGrid');
    if (!statsGrid) return;

    statsGrid.innerHTML = '';

    const icons = ['chart-line', 'users', 'percentage', 'dollar-sign'];
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

        // Format value: add ₹ only for Daily Earnings (index === 3)
        const formattedValue = index === 3 
            ? '₹' + formatNumber(stat.value)
            : formatNumber(stat.value) + (index === 2 ? '%' : '');

        card.innerHTML = `
            <div class="stat-icon" style="background: ${colors[index]}">
                <i class="fas fa-${icons[index]}"></i>
            </div>
            <div class="stat-content">
                <div class="stat-value">${formattedValue}</div>
                <div class="stat-label">${stat.label}</div>
                <div class="stat-change ${changeClass}">${changeSymbol}${stat.change}%</div>
            </div>
        `;

        statsGrid.appendChild(card);
    });
}
