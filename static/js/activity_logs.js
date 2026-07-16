function refreshLogs() {
    const limit = document.getElementById('limit').value;
    window.location.href = '/activity-logs?limit=' + limit;
}

function clearLogs() {
    if (!confirm('Hapus semua activity logs? Aksi ini tidak bisa dibatalkan.')) return;
    csrfFetch('/global-settings/clear-logs', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                document.getElementById('activityLogs').textContent = '';
                showToast('Activity logs cleared', 'success');
                location.reload();
            } else {
                showToast(data.error || 'Failed to clear logs', 'error');
            }
        })
        .catch(err => showToast('Network error clearing logs', 'error'));
}
