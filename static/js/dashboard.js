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
            document.getElementById('servers_container').innerHTML = '<div class="dashboard-empty is-error"><i class="fas fa-exclamation-circle"></i> Gagal memuat server</div>';
        });
}

function statusBadge(value, label, kind) {
    const zero = Number(value) === 0 ? ' is-zero' : '';
    return `<div class="status-badge ${kind}${zero}">
        <div class="status-value">${value}</div>
        <div class="status-label">${label}</div>
    </div>`;
}

function updateDashboard(servers, incomplete) {
    const container = document.getElementById('servers_container');

    if (!servers || servers.length === 0) {
        if (incomplete) {
            container.innerHTML = '<div class="dashboard-empty is-warn"><i class="fas fa-exclamation-triangle"></i> Snapshot data is incomplete. Host counts are not available.</div>';
        } else {
            container.innerHTML = '<div class="dashboard-empty"><i class="fas fa-inbox"></i> No servers found</div>';
        }
        return;
    }

    container.innerHTML = servers.map(server => {
        const hosts = server.hosts || {up: 0, down: 0, unreachable: 0, total: 0};
        const services = server.services || {ok: 0, warning: 0, critical: 0, unknown: 0, total: 0};
        const hasError = Boolean(server.fetch_error);
        let stateClass = 'is-ok';
        if (hosts.down > 0) {
            stateClass = 'is-down';
        } else if (hosts.unreachable > 0) {
            stateClass = 'is-unreachable';
        } else if (hasError) {
            stateClass = 'is-stale';
        }
        const portMeta = server.port
            ? `<div class="server-meta">Port ${escapeHtml(String(server.port))}</div>`
            : '';
        const errorNote = server.fetch_error
            ? `<div class="snapshot-error-note"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(String(server.fetch_error))}</div>`
            : '';
        return `
        <div class="server-card ${stateClass}">
            <div class="server-header">
                <div class="server-identity">
                    <div class="server-name"><i class="fas fa-server"></i><span class="server-name-text" title="${escapeHtml(server.name)}">${escapeHtml(server.name)}</span></div>
                    ${portMeta}
                </div>
                <a href="/nagios/${encodeURIComponent(server.name)}" target="_blank" class="btn-open"><i class="fas fa-external-link-alt"></i> Open</a>
            </div>
            ${errorNote}
            <div class="status-section">
                <div class="status-title">Hosts <span>${hosts.total}</span></div>
                <div class="status-grid status-grid-hosts">
                    ${statusBadge(hosts.up, 'UP', 'status-up')}
                    ${statusBadge(hosts.down, 'DOWN', 'status-down')}
                    ${statusBadge(hosts.unreachable, 'UNREACH', 'status-unreachable')}
                </div>
            </div>
            <div class="status-section">
                <div class="status-title">Services <span>${services.total}</span></div>
                <div class="status-grid status-grid-services">
                    ${statusBadge(services.ok, 'OK', 'status-up')}
                    ${statusBadge(services.warning, 'WARN', 'status-warning')}
                    ${statusBadge(services.critical, 'CRIT', 'status-down')}
                    ${statusBadge(services.unknown, 'UNK', 'status-unknown')}
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
