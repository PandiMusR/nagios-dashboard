function editPermissions(username) {
    document.getElementById('edit_username').value = username;
    
    fetch(`/user-permissions/get/${username}`)
        .then(r => r.json())
        .then(data => {
            Object.keys(data.permissions).forEach(perm => {
                const elem = document.querySelector(`input[name="${perm}"]`);
                if (elem) elem.checked = data.permissions[perm];
            });
            
            document.getElementById('editModal').classList.add('show');
        })
        .catch(err => {
            console.error('Error:', err);
            showToast('Failed to load permissions', 'error');
        });
}

function closeEditModal() {
    document.getElementById('editModal').classList.remove('show');
}

document.getElementById('editModal').addEventListener('click', function(e) {
    if (e.target === this) closeEditModal();
});
