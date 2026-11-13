function maskApiKey(key) {
    if (!key) return 'Not generated';
    if (key.length <= 4) return '••••';
    return '••••' + key.slice(-4);
}

function renderApiKey() {
    const input = document.getElementById('apiKeyDisplay');
    const key = input.dataset.key || '';
    const revealed = input.dataset.revealed === '1';
    input.value = revealed ? (key || 'Not generated') : maskApiKey(key);
}

function toggleApiKey() {
    const input = document.getElementById('apiKeyDisplay');
    const toggle = document.getElementById('apiKeyToggle');
    const revealed = input.dataset.revealed !== '1';
    input.dataset.revealed = revealed ? '1' : '0';
    renderApiKey();
    const icon = toggle.querySelector('i');
    icon.className = revealed ? 'fas fa-eye-slash' : 'fas fa-eye';
    const label = revealed ? 'Hide API key' : 'Show API key';
    toggle.title = label;
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('aria-pressed', revealed ? 'true' : 'false');
}

function generateApiKey() {
    if (!confirm('Generate a new API Key? The old key will stop working immediately.')) return;
    csrfFetch('/global-settings/generate-api-key', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const input = document.getElementById('apiKeyDisplay');
                input.dataset.key = data.api_key || '';
                renderApiKey();
                showToast('New API Key generated', 'success');
            } else {
                showToast(data.error || 'Operation failed', 'error');
            }
        })
        .catch(err => showToast('Request failed: network error', 'error'));
}

function copyApiKey() {
    const input = document.getElementById('apiKeyDisplay');
    const key = input.dataset.key || '';
    if (!key) {
        showToast('No API key', 'error');
        return;
    }
    navigator.clipboard.writeText(key).then(() => {
        showToast('API Key copied', 'success');
    }).catch(() => {
        const shown = input.value;
        const revealed = input.dataset.revealed === '1';
        input.value = key;
        input.select();
        document.execCommand('copy');
        input.value = revealed ? key : shown;
        showToast('API Key copied', 'success');
    });
}

function loadBackups() {
    fetch('/global-settings/backups')
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('backupList');
            if (!data.backups || data.backups.length === 0) {
                list.innerHTML = '<p class="gs-empty"><i class="fas fa-inbox"></i> No backups yet</p>';
                return;
            }
            
            list.innerHTML = data.backups.map((b, i) => `
                <div class="backup-item">
                    <div class="backup-info">
                        <strong>${b.name}</strong>
                        <small>${b.date} (${b.size})</small>
                    </div>
                    <div class="backup-actions">
                        <button onclick="restoreBackup('${b.name}')" class="btn-small btn-restore"><i class="fas fa-redo"></i> Pulihkan</button>
                        <button onclick="deleteBackup('${b.name}')" class="btn-small btn-delete"><i class="fas fa-trash"></i> Delete</button>
                    </div>
                </div>
            `).join('');
        })
        .catch(err => {
            document.getElementById('backupList').innerHTML = '<p class="gs-error"><i class="fas fa-exclamation-circle"></i> Gagal memuat backup</p>';
        });
}

function restoreBackup(name) {
    if (!confirm(`Pulihkan "${name}"? This will overwrite current config.`)) return;
    
    fetch('/global-settings/restore', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({backup_name: name})
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast('Pulihkand successfully', 'success');
            location.reload();
        } else {
            showToast(data.error || 'Pulihkan failed', 'error');
        }
    })
    .catch(err => showToast('Pulihkan error: ' + err.message, 'error'));
}

function deleteBackup(name) {
    if (!confirm(`Delete "${name}"?`)) return;
    
    fetch(`/global-settings/delete-backup/${name}`, {method: 'DELETE'})
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            loadBackups();
        } else {
            showToast('Delete failed', 'error');
        }
    });
}

function refreshLogs() {
    const el = document.getElementById('activityLogs');
    if (!el) {
        window.location.href = '/activity-logs';
        return;
    }
    fetch('/global-settings/logs')
        .then(r => r.text())
        .then(data => {
            el.textContent = data || 'No logs yet';
        });
}

function clearLogs() {
    if (!confirm('Clear all activity logs?')) return;

    csrfFetch('/global-settings/clear-logs', {method: 'POST'})
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            const el = document.getElementById('activityLogs');
            if (el) el.textContent = '';
            showToast('Activity logs cleared', 'success');
        }
    });
}

loadBackups();
