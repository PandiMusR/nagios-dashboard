let refreshInterval;
let countdownInterval;
let countdown = 30;

function showDashboardFetchErrors(errors) {
    const banner = document.getElementById('fetchErrorsBanner');
    if (!banner) return;
    if (!errors || !errors.length) {
        banner.hidden = true;
        banner.innerHTML = '';
        return;
    }

    const names = [];
    errors.forEach(function (msg) {
        const match = String(msg).match(/container\s+([^\s(]+)/i);
        if (match && names.indexOf(match[1]) === -1) {
            names.push(match[1]);
        }
    });
    const fromLabel = names.length ? names.join(', ') : 'one or more containers';

    const title = document.createElement('div');
    title.className = 'monitoring-fetch-alert-title';
    title.textContent = 'Warning: Data from ' + fromLabel + ' could not be retrieved. Displayed data is incomplete.';

    const list = document.createElement('ul');
    errors.forEach(function (msg) {
        const li = document.createElement('li');
        li.textContent = msg;
        list.appendChild(li);
    });

    banner.hidden = false;
    banner.replaceChildren(title, list);
}

function loadDashboardStats() {
    fetch('/dashboard/stats')
        .then(response => response.json())
        .then(data => {
            const errors = data.errors || (data.error ? [data.error] : []);
            showDashboardFetchErrors(errors);
            updateDashboard(data.servers || [], Boolean(data.incomplete || errors.length));
            document.getElementById('last_update').textContent = new Date().toLocaleTimeString('en-US', {hour12: false});
            countdown = 30;
        })
        .catch(error => {
            console.error('Error:', error);
            showDashboardFetchErrors(['Failed to load dashboard stats']);
            document.getElementById('servers_container').innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--color-danger-alt);"><i class="fas fa-exclamation-circle"></i> Gagal memuat server</div>';
        });
}

function updateDashboard(servers, incomplete) {
    const container = document.getElementById('servers_container');

    if (!servers || servers.length === 0) {
        if (incomplete) {
            container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--color-warning);"><i class="fas fa-exclamation-triangle"></i> Snapshot data is incomplete. Host counts are not available.</div>';
        } else {
            container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--text-muted);"><i class="fas fa-inbox"></i> No servers found</div>';
        }
        return;
    }

    container.innerHTML = servers.map(server => {
        const hosts = server.hosts || {up: 0, down: 0, unreachable: 0, total: 0};
        const services = server.services || {ok: 0, warning: 0, critical: 0, unknown: 0, total: 0};
        const hasDown = hosts.down > 0 || hosts.unreachable > 0;
        const hasError = Boolean(server.fetch_error);
        let borderColor = 'var(--color-success)';
        if (hasDown) {
            borderColor = 'var(--color-danger)';
        } else if (hasError) {
            borderColor = 'var(--color-warning)';
        }
        const errorNote = server.fetch_error
            ? `<div class="snapshot-error-note"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(String(server.fetch_error))}</div>`
            : '';
        return `
        <div class="server-card" style="border-left: 4px solid ${borderColor};">
            <div class="server-header">
                <div class="server-name"><i class="fas fa-server" style="margin-right: 0.5rem; color: var(--color-primary);"></i>${escapeHtml(server.name)}</div>
                <a href="/nagios/${encodeURIComponent(server.name)}" target="_blank" class="btn-open"><i class="fas fa-external-link-alt"></i> Open Nagios</a>
            </div>
            ${errorNote}
            
            <!-- System Resources -->
            <div class="resource-grid">
                <div class="resource-item">
                    <div class="resource-label"><i class="fas fa-microchip"></i> CPU</div>
                    <div class="resource-value">${escapeHtml(server.cpu)}</div>
                </div>
                <div class="resource-item">
                    <div class="resource-label"><i class="fas fa-memory"></i> Memory</div>
                    <div class="resource-value">${escapeHtml(server.memory)}</div>
                </div>
            </div>
            
            <!-- Hosts Status -->
            <div class="status-section">
                <div class="status-title">Hosts (${hosts.total})</div>
                <div class="status-grid">
                    <div class="status-badge status-up">
                        <div class="status-value">${hosts.up}</div>
                        <div class="status-label">UP</div>
                    </div>
                    <div class="status-badge status-down">
                        <div class="status-value">${hosts.down}</div>
                        <div class="status-label">DOWN</div>
                    </div>
                    <div class="status-badge status-warning">
                        <div class="status-value">${hosts.unreachable}</div>
                        <div class="status-label">UNREACH</div>
                    </div>
                </div>
            </div>
            
            <!-- Services Status -->
            <div class="status-section">
                <div class="status-title">Services (${services.total})</div>
                <div class="status-grid">
                    <div class="status-badge status-up">
                        <div class="status-value">${services.ok}</div>
                        <div class="status-label">OK</div>
                    </div>
                    <div class="status-badge status-warning">
                        <div class="status-value">${services.warning}</div>
                        <div class="status-label">WARN</div>
                    </div>
                    <div class="status-badge status-down">
                        <div class="status-value">${services.critical}</div>
                        <div class="status-label">CRIT</div>
                    </div>
                    <div class="status-badge status-unknown">
                        <div class="status-value">${services.unknown}</div>
                        <div class="status-label">UNKNOWN</div>
                    </div>
                </div>
            </div>
        </div>
    `}).join('');
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
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
