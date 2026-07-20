// Port checking functions
function checkPortStatus() {
    const port = document.getElementById('serverPort').value;
    const statusDiv = document.getElementById('portStatus');
    
    if (!port) {
        statusDiv.style.display = 'none';
        return;
    }
    
    fetch(`/api/servers/check-port/${port}`)
        .then(r => r.json())
        .then(data => {
            if (data.available) {
                statusDiv.style.display = 'block';
                statusDiv.style.background = 'var(--alert-success-bg)';
                statusDiv.style.color = 'var(--alert-success-color)';
                statusDiv.style.border = '1px solid var(--alert-success-color)';
                statusDiv.innerHTML = '<i class="fas fa-check-circle"></i> Port is available';
            } else {
                statusDiv.style.display = 'block';
                statusDiv.style.background = 'var(--alert-error-bg)';
                statusDiv.style.color = 'var(--alert-error-color)';
                statusDiv.style.border = '1px solid var(--alert-error-color)';
                statusDiv.innerHTML = '<i class="fas fa-exclamation-circle"></i> ' + data.reason;
            }
        })
        .catch(err => console.error('Port check error:', err));
}

function suggestPort() {
    const statusDiv = document.getElementById('portStatus');
    statusDiv.style.display = 'block';
    statusDiv.style.background = 'var(--alert-info-bg)';
    statusDiv.style.color = 'var(--alert-info-color)';
    statusDiv.style.border = '1px solid var(--alert-info-color)';
    statusDiv.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Finding available port...';
    
    fetch('/api/servers/get-available-port')
        .then(r => r.json())
        .then(data => {
            if (data.available) {
                document.getElementById('serverPort').value = data.port;
                statusDiv.style.background = 'var(--alert-success-bg)';
                statusDiv.style.color = 'var(--alert-success-color)';
                statusDiv.style.border = '1px solid var(--alert-success-color)';
                statusDiv.innerHTML = `<i class="fas fa-check-circle"></i> Suggested port: ${data.port} (Proxy: ${data.proxy_port})`;
                checkPortStatus();
            } else {
                statusDiv.style.background = 'var(--alert-error-bg)';
                statusDiv.style.color = 'var(--alert-error-color)';
                statusDiv.style.border = '1px solid var(--alert-error-color)';
                statusDiv.innerHTML = '<i class="fas fa-exclamation-circle"></i> ' + data.reason;
            }
        })
        .catch(err => {
            console.error('Port suggestion error:', err);
            statusDiv.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Error checking available ports';
        });
}

// Add event listener for port input
document.addEventListener('DOMContentLoaded', function() {
    const portInput = document.getElementById('serverPort');
    if (portInput) {
        portInput.addEventListener('change', checkPortStatus);
        portInput.addEventListener('blur', checkPortStatus);
    }
});

let batchAction = null;
let batchServers = [];

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.server-checkbox');
    checkboxes.forEach(cb => cb.checked = selectAll.checked);
}

function getSelectedServers() {
    const checkboxes = document.querySelectorAll('.server-checkbox:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

function showBatchModal(action, servers) {
    if (servers.length === 0) {
        showToast('Select at least one server', 'warning');
        return;
    }
    
    batchAction = action;
    batchServers = servers;
    
    const modal = document.getElementById('batchModal');
    const title = document.getElementById('batchModalTitle');
    const message = document.getElementById('batchModalMessage');
    const serverList = document.getElementById('batchModalServerList');
    const confirmBtn = document.getElementById('batchModalConfirm');
    
    const actions = {
        'start': { title: 'Start Servers', message: `Start ${servers.length} server(s)?`, color: 'var(--color-success)' },
        'restart': { title: 'Restart Servers', message: `Restart ${servers.length} server(s)?`, color: 'var(--color-warning)' },
        'delete': { title: 'Delete Servers', message: `Delete ${servers.length} server(s)? This cannot be undone!`, color: 'var(--color-danger)' }
    };
    
    const actionConfig = actions[action];
    title.textContent = actionConfig.title;
    message.textContent = actionConfig.message;
    confirmBtn.style.background = actionConfig.color;
    confirmBtn.textContent = action.charAt(0).toUpperCase() + action.slice(1);
    
    serverList.innerHTML = servers.map(s => 
        `<div style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); color: var(--text-secondary);">• ${s}</div>`
    ).join('');
    
    modal.classList.add('show');
}

function closeBatchModal() {
    document.getElementById('batchModal').classList.remove('show');
    batchAction = null;
    batchServers = [];
}

function executeBatchAction() {
    if (!batchAction || batchServers.length === 0) return;
    
    const confirmBtn = document.getElementById('batchModalConfirm');
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Processing...';
    
    fetch(`/servers/batch-${batchAction}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({servers: batchServers})
    })
    .then(r => r.json())
    .then(data => {
        closeBatchModal();
        if (data.success) {
            showToast('Servers ' + batchAction + 'ed', 'success');
            location.reload();
        } else {
            showToast(data.error || 'Operation failed', 'error');
            confirmBtn.disabled = false;
        }
    })
    .catch(err => {
        closeBatchModal();
        showToast('Network error', 'error');
        confirmBtn.disabled = false;
    });
}

function batchStart() { showBatchModal('start', getSelectedServers()); }
function batchRestart() { showBatchModal('restart', getSelectedServers()); }
function batchDelete() { showBatchModal('delete', getSelectedServers()); }

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('batchModalConfirm').onclick = executeBatchAction;
});

// Add Server Form
document.getElementById('addServerForm').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const formData = new FormData(this);
    const serverName = formData.get('name');
    const serverPort = formData.get('port');
    
    // Validate inputs
    if (!serverName || !serverPort) {
        showToast('Fill in all required fields', 'warning');
        return;
    }
    
    if (serverPort < 1000 || serverPort > 65535) {
        showToast('Port must be 1000-65535', 'warning');
        return;
    }
    
    document.getElementById('loadingOverlay').classList.add('show');
    
    fetch('/servers/add', {
        method: 'POST',
        body: formData
    })
    .then(r => {
        if (!r.ok) {
            throw new Error(`HTTP ${r.status}: ${r.statusText}`);
        }
        return r.json();
    })
    .then(data => {
        if (data.success) {
            showToast('Server creation started', 'success');
            checkServerStatus(serverName);
        } else {
            document.getElementById('loadingOverlay').classList.remove('show');
            showToast(data.error || 'Operation failed', 'error');
            console.error('Server creation error:', data);
        }
    })
    .catch(err => {
        document.getElementById('loadingOverlay').classList.remove('show');
        console.error('Fetch error:', err);
        showToast('Error: ' + err.message, 'error');
    });
});

function checkServerStatus(serverName) {
    let attempts = 0;
    const maxAttempts = 60; // 2 minutes with 2 second intervals
    
    function check() {
        if (attempts >= maxAttempts) {
            document.getElementById('loadingOverlay').classList.remove('show');
            showToast('Server creation taking longer than expected', 'warning');
            return;
        }
        
        fetch('/servers/check/' + serverName)
            .then(r => {
                if (!r.ok) throw new Error('Check failed');
                return r.json();
            })
            .then(data => {
                if (data.exists) {
                    location.reload();
                } else {
                    attempts++;
                    setTimeout(check, 2000);
                }
            })
            .catch(err => {
                attempts++;
                if (attempts < maxAttempts) {
                    setTimeout(check, 2000);
                } else {
                    document.getElementById('loadingOverlay').classList.remove('show');
                    showToast('Server creation timed out', 'error');
                }
            });
    }
    
    check();
}

// Plugin Modal Functions
function openPluginModal(serverName) {
    document.getElementById('pluginServerName').textContent = serverName;
    document.getElementById('uploadServerName').value = serverName;
    document.getElementById('pluginModal').classList.add('show');
    loadPluginList(serverName);
}

function closePluginModal() {
    document.getElementById('pluginModal').classList.remove('show');
}

function loadPluginList(serverName) {
    fetch('/servers/plugins/' + serverName)
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('pluginList');
            if (data.plugins && data.plugins.length > 0) {
                list.innerHTML = data.plugins.map(p => `
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; background: var(--bg-secondary); border-radius: 6px; margin-bottom: 0.5rem;">
                        <div>
                            <strong style="color: var(--text-primary);">${p.name}</strong>
                            <span style="color: var(--text-secondary); font-size: 0.8rem; margin-left: 0.5rem;">${p.size}</span>
                        </div>
                        <button onclick="deletePlugin('${serverName}', '${p.name}')" class="btn-sm btn-danger">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                `).join('');
            } else {
                list.innerHTML = '<p style="text-align: center; color: var(--text-muted); margin: 0;">No plugins found</p>';
            }
        });
}

function deletePlugin(serverName, pluginName) {
    if (!confirm('Delete: ' + pluginName + '?')) return;
    
    fetch('/servers/plugins/' + serverName + '/' + pluginName, {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
            if (data.success) loadPluginList(serverName);
            else showToast('Failed to delete plugin', 'error');
        });
}

document.getElementById('uploadPluginForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const formData = new FormData(this);
    const serverName = document.getElementById('uploadServerName').value;
    
    fetch('/servers/plugins/upload', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            this.reset();
            loadPluginList(serverName);
            showToast('Plugin uploaded', 'success');
        } else {
            showToast(data.error || 'Plugin upload failed', 'error');
        }
    });
});

// Config Check Modal
function checkConfig(serverName) {
    document.getElementById('configServerName').textContent = serverName;
    document.getElementById('configOutput').textContent = 'Checking configuration...';
    document.getElementById('configModal').classList.add('show');
    
    fetch('/servers/check-config/' + serverName)
        .then(r => r.json())
        .then(data => {
            const output = document.getElementById('configOutput');
            if (data.success) {
                output.style.color = 'var(--color-success)';
                output.textContent = data.output;
            } else {
                output.style.color = 'var(--color-danger)';
                output.textContent = (data.error || data.output || 'Unknown error');
            }
        })
        .catch(err => {
            const output = document.getElementById('configOutput');
            output.style.color = 'var(--color-danger)';
            output.textContent = 'Error: ' + err;
        });
}

function closeConfigModal() {
    document.getElementById('configModal').classList.remove('show');
}

// Close modals on outside click
document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('show');
        }
    });
});
