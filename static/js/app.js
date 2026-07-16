// Toast notification system
        function showToast(msg, type = 'info') {
            const container = document.getElementById('toastContainer');
            const icons = { success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };
            const toast = document.createElement('div');
            toast.className = `toast toast-${type}`;
            toast.innerHTML = `<i class="fas ${icons[type] || icons.info} toast-icon"></i><span>${msg}</span>`;
            toast.addEventListener('click', () => toast.remove());
            container.appendChild(toast);
            setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 4000);
        }

        // Dark mode
        function initDarkMode() {
            const saved = localStorage.getItem('theme');
            if (saved === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
                updateDarkModeIcon(true);
            }
        }
        function toggleDarkMode() {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('theme', 'light');
                updateDarkModeIcon(false);
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                localStorage.setItem('theme', 'dark');
                updateDarkModeIcon(true);
            }
        }
        function updateDarkModeIcon(isDark) {
            const btn = document.getElementById('darkModeBtn');
            if (btn) {
                btn.innerHTML = isDark ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';
            }
        }
        initDarkMode();

        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const content = document.getElementById('content');
            sidebar.classList.toggle('collapsed');
            content.classList.toggle('expanded');
            const burger = document.querySelector('.burger');
            if (burger) burger.setAttribute('aria-expanded', !sidebar.classList.contains('collapsed'));
        }


        function toggleSubmenu(event, menuId) {
            event.preventDefault();
            const submenu = document.getElementById(menuId);
            const toggle = event.currentTarget;
            
            submenu.classList.toggle('show');
            toggle.classList.toggle('active');
            const expanded = submenu.classList.contains('show');
            toggle.setAttribute('aria-expanded', expanded);
        }
        
        // Auto-expand submenu if current page is in it
        document.addEventListener('DOMContentLoaded', function() {
            const activeLinks = document.querySelectorAll('.submenu a.active');
            activeLinks.forEach(link => {
                const submenu = link.closest('.submenu');
                const toggle = submenu.previousElementSibling;
                if (submenu && toggle) {
                    submenu.classList.add('show');
                    toggle.classList.add('active');
                    toggle.setAttribute('aria-expanded', 'true');
                }
            });
        });
        
        // CSRF token helper for AJAX fetch calls
        function csrfFetch(url, options) {
            options = options || {};
            options.headers = options.headers || {};
            var el = document.querySelector('meta[name="csrf-token"]');
            if (el) options.headers['X-CSRFToken'] = el.content;
            return fetch(url, options);
        }

        // Change Password Modal Functions
        function openChangePasswordModal() {
            const modal = document.getElementById('changePasswordModal');
            const form = document.getElementById('changePasswordForm');
            if (form) form.reset();
            modal.classList.add('show');
        }
        
        function closeChangePasswordModal() {
            const modal = document.getElementById('changePasswordModal');
            const alertBox = document.querySelector('.password-alert');
            modal.classList.remove('show');
            if (alertBox) alertBox.style.display = 'none';
        }
        
        function submitChangePassword() {
            const oldPassword = document.getElementById('oldPassword').value;
            const newPassword = document.getElementById('newPassword').value;
            const confirmPassword = document.getElementById('confirmPassword').value;
            const alertBox = document.querySelector('.password-alert');
            
            // Validation
            if (!oldPassword || !newPassword || !confirmPassword) {
                showAlert(alertBox, 'error', 'Semua field harus diisi');
                return;
            }
            
            if (newPassword !== confirmPassword) {
                showAlert(alertBox, 'error', 'Password baru tidak cocok');
                return;
            }
            
            if (newPassword.length < 8) {
                showAlert(alertBox, 'error', 'Password minimal 8 karakter');
                return;
            }
            
            // Send request to change password
            fetch('/api/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    old_password: oldPassword,
                    new_password: newPassword
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showAlert(alertBox, 'success', 'Password berhasil diubah');
                    setTimeout(() => {
                        closeChangePasswordModal();
                    }, 2000);
                } else {
                    showAlert(alertBox, 'error', data.message || 'Gagal mengubah password');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showAlert(alertBox, 'error', 'Terjadi kesalahan pada server');
            });
        }
        
        function showAlert(alertBox, type, message) {
            if (!alertBox) return;
            alertBox.className = `password-alert ${type}`;
            alertBox.innerHTML = message;
            alertBox.style.display = 'block';
        }
        
        function logout() {
            if (confirm('Anda yakin ingin logout?')) {
                window.location.href = '/logout';
            }
        }
        
        // Close modal when clicking outside
        document.addEventListener('click', function(event) {
            const modal = document.getElementById('changePasswordModal');
            if (modal && event.target === modal) {
                closeChangePasswordModal();
            }
        });
        
        // Close modal with Escape key
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeChangePasswordModal();
            }
        });

        // === Keyboard Shortcuts for NOC (not in input/textarea) ===
        document.addEventListener('keydown', function(e) {
            const tag = document.activeElement.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            
            // R — refresh current page data
            if (e.key === 'r' && !e.ctrlKey && !e.metaKey) {
                const refreshBtn = document.querySelector('[id*="refresh"], [class*="refresh-btn"], button[onclick*="loadMonitoring"], button[onclick*="refreshMonitors"]');
                if (refreshBtn) { refreshBtn.click(); return; }
                const autoRefresh = document.getElementById('autoRefreshToggle');
                if (autoRefresh) { location.reload(); }
            }
            
            // / — focus search input
            if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
                const searchInput = document.querySelector('input[type="search"], input[placeholder*="earch"], input[placeholder*="Cari"], input[id*="search"]');
                if (searchInput) { e.preventDefault(); searchInput.focus(); }
            }
            
            // Ctrl+S — save/submit active form
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                const submitBtn = document.querySelector('button[type="submit"], button[onclick*="save"], button:not([onclick*="logout"]):not([onclick*="delete"]):not([id*="delete"])[class*="btn-primary"], [class*="save-btn"]');
                if (submitBtn && submitBtn.offsetParent !== null) submitBtn.click();
            }
        });
