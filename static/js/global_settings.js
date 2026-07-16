function generateApiKey() {
    if (!confirm('Generate a new API Key? The old key will stop working immediately.')) return;
    csrfFetch('/global-settings/generate-api-key', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                document.getElementById('apiKeyDisplay').value = data.api_key;
                showToast('New API Key generated', 'success');
            } else {
                showToast(data.error || 'Operation failed', 'error');
            }
        })
        .catch(err => showToast('Request failed: network error', 'error'));
}

function copyApiKey() {
    const input = document.getElementById('apiKeyDisplay');
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('API Key copied', 'success');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('API Key copied', 'success');
    });
}

function loadBackups() {
    fetch('/global-settings/backups')
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('backupList');
            if (!data.backups || data.backups.length === 0) {
                list.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 2rem;"><i class="fas fa-inbox"></i> No backups yet</p>';
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
            document.getElementById('backupList').innerHTML = '<p style="color: var(--color-danger-alt);"><i class="fas fa-exclamation-circle"></i> Gagal memuat backup</p>';
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
    fetch('/global-settings/logs')
        .then(r => r.text())
        .then(data => {
            document.getElementById('activityLogs').textContent = data || 'No logs yet';
        });
}

function clearLogs() {
    if (!confirm('Clear all activity logs?')) return;
    
    csrfFetch('/global-settings/clear-logs', {method: 'POST'})
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            document.getElementById('activityLogs').textContent = '';
            showToast('Activity logs cleared', 'success');
        }
    });
}

loadBackups();
