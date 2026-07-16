async function loadMonitors() {
    try {
        const response = await fetch('/api/monitoring-intens/monitors');
        
        // Check if response is OK
        if (!response.ok) {
            document.getElementById('monitorList').innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>HTTP Error ${response.status}: ${response.statusText}</p>
                </div>
            `;
            return;
        }
        
        let data;
        try {
            data = await response.json();
        } catch (parseError) {
            // Response is not JSON
            const text = await response.text();
            document.getElementById('monitorList').innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>Invalid response from server</p>
                    <small style="color: var(--text-muted);">${escapeHtml(text.substring(0, 100))}</small>
                </div>
            `;
            return;
        }
        
        if (!data.success) {
            document.getElementById('monitorList').innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>${data.error || 'Gagal memuat monitor'}</p>
                </div>
            `;
            return;
        }

        if (!data.monitors || data.monitors.length === 0) {
            document.getElementById('monitorList').innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <p>Tidak ada monitor ditemukan. Add hosts with "Monitor in Uptime Kuma" enabled in Host Manager.</p>
                    <p style="font-size: 0.9rem; color: var(--text-muted); margin-top: 1rem;">Note: Uptime Kuma integration requires proper configuration in Global Settings.</p>
                </div>
            `;
            return;
        }

        const html = data.monitors.map(monitor => {
            const status = getStatusBadge(monitor.status);
            const heartbeats = monitor.heartbeats || [];
            const uptime = monitor.uptime || 0;
            
            return `
                <div class="monitor-card">
                    <div class="monitor-header">
                        <div class="monitor-title">
                            <i class="fas fa-${getMonitorIcon(monitor.type)}"></i>
                            <span>${escapeHtml(monitor.name)}</span>
                        </div>
                        <span class="monitor-status ${status.class}">${status.text}</span>
                    </div>

                    <div class="monitor-info">
                        <div class="info-item">
                            <span class="info-label">Type</span>
                            <span class="info-value">${escapeHtml(monitor.type || 'Unknown')}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Hostname/IP</span>
                            <span class="info-value">${escapeHtml(monitor.hostname || monitor.url || 'N/A')}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Last Check</span>
                            <span class="info-value">${formatTime(monitor.lastHeartbeat)}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Uptime (24h)</span>
                            <span class="info-value">${(uptime * 100).toFixed(2)}%</span>
                        </div>
                    </div>

                    ${heartbeats.length > 0 ? `
                    <div style="margin-bottom: 1rem;">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem; text-transform: uppercase; font-weight: 700;">Recent Status (Last 48 hours)</div>
                        <div class="heartbeat-chart">
                            ${heartbeats.map(hb => `
                                <div class="heartbeat-bar ${getHeartbeatClass(hb.status)}" title="${hb.msg || ''} - ${new Date(hb.time).toLocaleString()}"></div>
                            `).join('')}
                        </div>
                    </div>
                    ` : ''}

                    <div class="uptime-section">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.75rem; text-transform: uppercase; font-weight: 700;">Uptime Trend</div>
                        <div class="uptime-bars">
                            <div class="uptime-item">
                                <div class="uptime-label">24h</div>
                                <div class="uptime-value">${(uptime * 100).toFixed(1)}%</div>
                                <div class="uptime-bar">
                                    <div class="uptime-bar-fill" style="width: ${uptime * 100}%"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    ${monitor.avgPing ? `
                    <div class="ping-value"><i class="fas fa-tachometer-alt"></i> Avg Ping: ${monitor.avgPing.toFixed(0)}ms</div>
                    ` : ''}

                    <div style="margin-top: 1rem; display: flex; gap: 0.75rem;">
                        <button onclick="removeMonitor(${monitor.id})" class="btn-primary btn-danger" style="font-size: 0.85rem;">
                            <i class="fas fa-trash"></i> Remove Monitor
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        document.getElementById('monitorList').innerHTML = html;
    } catch (error) {
        console.error('Error loading monitors:', error);
        document.getElementById('monitorList').innerHTML = `
            <div class="empty-state">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Error loading monitors: ${error.message}</p>
            </div>
        `;
    }
}

function getStatusBadge(status) {
    const statuses = {
        0: { text: 'DOWN', class: 'status-down' },
        1: { text: 'UP', class: 'status-up' },
        2: { text: 'PENDING', class: 'status-pending' },
        3: { text: 'MAINTENANCE', class: 'status-maintenance' }
    };
    return statuses[status] || { text: 'UNKNOWN', class: 'status-pending' };
}

function getHeartbeatClass(status) {
    const classes = {
        0: 'down',
        1: 'up',
        2: 'pending',
        3: 'maintenance'
    };
    return classes[status] || 'pending';
}

function getMonitorIcon(type) {
    const icons = {
        'ping': 'network-wired',
        'http': 'globe',
        'https': 'lock',
        'dns': 'server',
        'tcp': 'plug',
        'udp': 'plug',
        'smtp': 'envelope',
        'pop3': 'envelope',
        'imap': 'envelope',
        'ftp': 'folder'
    };
    return icons[type] || 'heartbeat';
}

function formatTime(time) {
    if (!time) return 'Never';
    const date = new Date(time);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    return date.toLocaleDateString();
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

async function removeMonitor(monitorId) {
    if (!confirm('Remove this monitor?')) return;
    
    try {
        const response = await fetch(`/api/monitoring-intens/monitors/${monitorId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        
        if (data.success) {
            loadMonitors();
        } else {
            showToast(data.error || 'Failed to remove monitor', 'error');
        }
    } catch (error) {
        showToast('Network error removing monitor', 'error');
    }
}

// Load monitors on page load
loadMonitors();

// Refresh every 30 seconds
setInterval(loadMonitors, 30000);
