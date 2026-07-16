function validateCrReset(form) {
    const hours = form.querySelector('[name="cr_reset_hours"]').value.trim();
    const interval = form.querySelector('[name="cr_reset_interval_days"]').value;
    const grace = form.querySelector('[name="cr_reset_grace_hours"]').value;

    // Validate hours: only numbers and commas
    if (hours && !/^[0-9, ]*$/.test(hours)) {
        showToast('Reset Hours: hanya angka dan koma (contoh: 03,15)', 'warning');
        return false;
    }

    // Validate each hour is 0-23
    if (hours) {
        const parts = hours.split(',').map(h => parseInt(h.trim())).filter(h => !isNaN(h));
        for (const h of parts) {
            if (h < 0 || h > 23) {
                showToast('Jam harus 0-23', 'warning');
                return false;
            }
        }
    }

    // Validate interval
    if (interval < 0 || interval > 365) {
        showToast('Interval harus 0-365 hari', 'warning');
        return false;
    }

    // Validate grace period
    if (grace < 0 || grace > 720) {
        showToast('Grace Period harus 0-720 jam', 'warning');
        return false;
    }

    return true;
}

function testSound(elementId) {
    const element = document.getElementById(elementId);
    if (!element.files || !element.files[0]) {
        showToast('Select a sound file first', 'warning');
        return;
    }
    
    const reader = new FileReader();
    reader.onload = function(e) {
        const audio = new Audio();
        audio.src = e.target.result;
        audio.play();
    };
    reader.readAsDataURL(element.files[0]);
}

function editCategory(category, useServicePlugin) {
    document.getElementById('editCategoryName').value = category;
    document.getElementById('editCategoryNameDisplay').value = category;
    document.getElementById('editUseServicePlugin').value = useServicePlugin ? 'true' : 'false';
    document.getElementById('editCategoryModal').style.display = 'flex';
}

function closeEditCategoryModal() {
    document.getElementById('editCategoryModal').style.display = 'none';
}

function openAddCategoryModal() {
    document.getElementById('addCategoryModal').style.display = 'flex';
}

function closeAddCategoryModal() {
    document.getElementById('addCategoryModal').style.display = 'none';
}

document.getElementById('editCategoryModal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeEditCategoryModal();
    }
});

document.getElementById('addCategoryModal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeAddCategoryModal();
    }
});
