function togglePermissions() {
    const role = document.getElementById('roleSelect').value;
    const permSection = document.getElementById('permissionsSection');
    permSection.style.display = role === 'admin' ? 'none' : 'block';
}

togglePermissions();
