let refreshInterval;
let countdownInterval;
let countdown = 30;

function loadDashboardStats() {
    fetch('/dashboard/stats')
        .then(response => response.json())
        .then(data => {
            updateDashboard(data.servers);
            document.getElementById('last_update').textContent = new Date().toLocaleTimeString('en-US', {hour12: false});
            countdown = 30;
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('servers_container').innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--color-danger-alt);"><i class="fas fa-exclamation-circle"></i> Gagal memuat server</div>';
        });
}

function updateDashboard(servers) {
    const container = document.getElementById('servers_container');
    
    if (servers.length === 0) {
        container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--text-muted);"><i class="fas fa-inbox"></i> No servers found</div>';
        return;
    }
    
    container.innerHTML = servers.map(server => {
        const hasDown = server.hosts.down > 0;
        const borderColor = hasDown ? 'var(--color-danger)' : 'var(--color-success)';
        return `
        <div class="server-card" style="border-left: 4px solid ${borderColor};">
            <div class="server-header">
                <div class="server-name"><i class="fas fa-server" style="margin-right: 0.5rem; color: var(--color-primary);"></i>${server.name}</div>
                <a href="/nagios/${server.name}" target="_blank" class="btn-open"><i class="fas fa-external-link-alt"></i> Open Nagios</a>
            </div>
            
            <!-- System Resources -->
            <div class="resource-grid">
                <div class="resource-item">
                    <div class="resource-label"><i class="fas fa-microchip"></i> CPU</div>
                    <div class="resource-value">${server.cpu}</div>
                </div>
                <div class="resource-item">
                    <div class="resource-label"><i class="fas fa-memory"></i> Memory</div>
                    <div class="resource-value">${server.memory}</div>
                </div>
            </div>
            
            <!-- Hosts Status -->
            <div class="status-section">
                <div class="status-title">Hosts (${server.hosts.total})</div>
                <div class="status-grid">
                    <div class="status-badge status-up">
                        <div class="status-value">${server.hosts.up}</div>
                        <div class="status-label">UP</div>
                    </div>
                    <div class="status-badge status-down">
                        <div class="status-value">${server.hosts.down}</div>
                        <div class="status-label">DOWN</div>
                    </div>
                    <div class="status-badge status-warning">
                        <div class="status-value">${server.hosts.unreachable}</div>
                        <div class="status-label">UNREACH</div>
                    </div>
                </div>
            </div>
            
            <!-- Services Status -->
            <div class="status-section">
                <div class="status-title">Services (${server.services.total})</div>
                <div class="status-grid">
                    <div class="status-badge status-up">
                        <div class="status-value">${server.services.ok}</div>
                        <div class="status-label">OK</div>
                    </div>
                    <div class="status-badge status-warning">
                        <div class="status-value">${server.services.warning}</div>
                        <div class="status-label">WARN</div>
                    </div>
                    <div class="status-badge status-down">
                        <div class="status-value">${server.services.critical}</div>
                        <div class="status-label">CRIT</div>
                    </div>
                    <div class="status-badge status-unknown">
                        <div class="status-value">${server.services.unknown}</div>
                        <div class="status-label">UNKNOWN</div>
                    </div>
                </div>
            </div>
        </div>
    `}).join('');
}

function startAutoRefresh() {
    loadDashboardStats();
    
    refreshInterval = setInterval(() => {
        loadDashboardStats();
    }, 30000);
    
    countdownInterval = setInterval(() => {
        countdown--;
        if (countdown < 0) countdown = 30;
        document.getElementById('refresh_countdown').textContent = countdown;
    }, 1000);
}

window.addEventListener('load', startAutoRefresh);
window.addEventListener('beforeunload', () => {
    if (refreshInterval) clearInterval(refreshInterval);
    if (countdownInterval) clearInterval(countdownInterval);
});
