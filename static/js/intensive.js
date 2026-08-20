(function () {
    const hostSelect = document.getElementById('imHost');
    const refreshBtn = document.getElementById('imRefresh');
    const metaEl = document.getElementById('imMeta');
    const chartWrap = document.querySelector('.im-chart-wrap');
    const canvas = document.getElementById('imChart');
    const rangeBtns = document.querySelectorAll('.im-range-btn');

    let currentHost = '';
    let currentRange = '24h';
    let chart = null;
    let lastSeries = { labels: [], latency: [] };
    let lastHosts = [];
    let loading = false;

    function themeColors() {
        const dark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            text: dark ? '#94a3b8' : '#64748b',
            grid: dark ? 'rgba(148, 163, 184, 0.15)' : 'rgba(148, 163, 184, 0.25)',
            line: dark ? '#818cf8' : '#4f46e5',
            fill: dark ? 'rgba(129, 140, 248, 0.18)' : 'rgba(79, 70, 229, 0.12)',
        };
    }

    function formatLatency(value) {
        if (value === null || value === undefined) return '—';
        return Number(value).toFixed(value >= 100 ? 0 : 1) + ' ms';
    }

    function formatTs(value) {
        if (!value) return '';
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return value.replace('T', ' ');
        return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function setStatus(el, status) {
        el.classList.remove('is-up', 'is-down', 'is-unknown');
        if (status === 'up') {
            el.textContent = 'UP';
            el.classList.add('is-up');
        } else if (status === 'down') {
            el.textContent = 'DOWN';
            el.classList.add('is-down');
        } else {
            el.textContent = '—';
            el.classList.add('is-unknown');
        }
    }

    function fillHosts(hosts, selectedId) {
        const previous = selectedId || hostSelect.value;
        hostSelect.innerHTML = '';
        if (!hosts.length) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'Tidak ada host';
            hostSelect.appendChild(opt);
            return;
        }
        hosts.forEach(function (host) {
            const opt = document.createElement('option');
            opt.value = host.id;
            const badge = host.last_status === 'up' ? 'UP' : host.last_status === 'down' ? 'DOWN' : '—';
            opt.textContent = (host.name || host.id) + ' (' + host.address + ') · ' + badge;
            hostSelect.appendChild(opt);
        });
        if (previous && Array.from(hostSelect.options).some(function (o) { return o.value === previous; })) {
            hostSelect.value = previous;
        }
        currentHost = hostSelect.value;
    }

    function renderChart(series) {
        const colors = themeColors();
        const hasPoints = series.labels && series.labels.length > 0;
        chartWrap.classList.toggle('is-empty', !hasPoints);
        lastSeries = {
            labels: series.labels || [],
            latency: series.latency || [],
        };

        const data = {
            labels: series.labels || [],
            datasets: [{
                label: 'Latency (ms)',
                data: series.latency || [],
                borderColor: colors.line,
                backgroundColor: colors.fill,
                borderWidth: 2,
                pointRadius: hasPoints && series.labels.length < 80 ? 2 : 0,
                pointHoverRadius: 4,
                fill: true,
                tension: 0.25,
                spanGaps: true,
            }],
        };
        const options = {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: function (items) {
                            return items.length ? formatTs(series.labels[items[0].dataIndex]) : '';
                        },
                        label: function (item) {
                            return item.parsed.y === null ? 'Timeout / no reply' : formatLatency(item.parsed.y);
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        color: colors.text,
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                        callback: function (value) {
                            const label = this.getLabelForValue(value);
                            return formatTs(label);
                        },
                    },
                    grid: { color: colors.grid },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        color: colors.text,
                        callback: function (value) { return value + ' ms'; },
                    },
                    grid: { color: colors.grid },
                    title: { display: true, text: 'Latency (ms)', color: colors.text },
                },
            },
        };

        if (chart) {
            chart.data = data;
            chart.options = options;
            chart.update('none');
            return;
        }
        if (!canvas || typeof Chart === 'undefined') return;
        chart = new Chart(canvas, { type: 'line', data: data, options: options });
    }

    async function loadData() {
        if (loading) return;
        loading = true;
        refreshBtn.disabled = true;
        const params = new URLSearchParams({ range: currentRange });
        if (currentHost) params.set('host', currentHost);
        try {
            const response = await fetch('/api/intensive/data?' + params.toString());
            const data = await response.json();
            if (!response.ok || !data.success) {
                metaEl.textContent = (data && data.error) ? data.error : 'Gagal memuat data';
                renderChart({ labels: [], latency: [] });
                return;
            }
            fillHosts(data.hosts || [], (data.host && data.host.id) || currentHost);
            lastHosts = data.hosts || [];
            renderManageList(lastHosts);
            const stats = data.stats || {};
            setStatus(document.getElementById('imStatStatus'), stats.status);
            document.getElementById('imStatLatency').textContent = formatLatency(stats.latency_ms);
            document.getElementById('imStatAvg').textContent = formatLatency(stats.avg_latency_ms);
            document.getElementById('imStatUptime').textContent =
                stats.uptime_pct === null || stats.uptime_pct === undefined ? '—' : stats.uptime_pct.toFixed(1) + '%';

            const host = data.host;
            if (!host) {
                metaEl.textContent = 'Belum ada host di config/intensive_hosts.json';
            } else if (!stats.samples) {
                metaEl.textContent = (host.name || host.id) + ' · belum ada sampel di rentang ini';
            } else {
                metaEl.textContent = (host.name || host.id) + ' · ' + stats.samples + ' samples · range ' + data.range;
            }
            renderChart(data.series || { labels: [], latency: [] });
        } catch (err) {
            metaEl.textContent = 'Tidak bisa terhubung ke API';
            renderChart({ labels: [], latency: [] });
        } finally {
            loading = false;
            refreshBtn.disabled = false;
        }
    }

    hostSelect.addEventListener('change', function () {
        currentHost = hostSelect.value;
        loadData();
    });
    refreshBtn.addEventListener('click', loadData);
    rangeBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            rangeBtns.forEach(function (b) { b.classList.remove('is-active'); });
            btn.classList.add('is-active');
            currentRange = btn.getAttribute('data-range');
            loadData();
        });
    });

    const themeObserver = new MutationObserver(function () {
        if (chart) renderChart(lastSeries);
    });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    loadData();
    setInterval(function () {
        if (document.hidden) return;
        loadData();
    }, 20000);

    const modal = document.getElementById('imHostModal');
    const manageBtn = document.getElementById('imManage');
    const modalClose = document.getElementById('imModalClose');
    const addForm = document.getElementById('imAddForm');
    const modalError = document.getElementById('imModalError');
    const hostListEl = document.getElementById('imHostList');

    function showModalError(message) {
        if (!modalError) return;
        if (!message) {
            modalError.hidden = true;
            modalError.textContent = '';
            return;
        }
        modalError.hidden = false;
        modalError.textContent = message;
    }

    function openModal() {
        showModalError('');
        renderManageList(lastHosts);
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
    }

    function closeModal() {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }

    function renderManageList(hosts) {
        if (!hostListEl) return;
        hostListEl.innerHTML = '';
        if (!hosts.length) {
            hostListEl.innerHTML = '<p class="im-host-row-meta">Belum ada host. Tambah target di form atas.</p>';
            return;
        }
        hosts.forEach(function (host) {
            const row = document.createElement('div');
            row.className = 'im-host-row';
            const info = document.createElement('div');
            info.className = 'im-host-row-info';
            info.innerHTML = '<div class="im-host-row-name"></div><div class="im-host-row-meta"></div>';
            info.querySelector('.im-host-row-name').textContent = host.name || host.id;
            info.querySelector('.im-host-row-meta').textContent =
                (host.address || '') + ' · every ' + (host.interval_seconds || 20) + 's';
            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'btn-danger';
            del.textContent = 'Delete';
            del.addEventListener('click', function () { deleteHost(host.id); });
            row.appendChild(info);
            row.appendChild(del);
            hostListEl.appendChild(row);
        });
    }

    async function deleteHost(hostId) {
        if (!hostId || typeof csrfFetch !== 'function') return;
        if (!window.confirm('Hapus host ini dari intensive monitoring?')) return;
        showModalError('');
        try {
            const response = await csrfFetch('/api/intensive/hosts/' + encodeURIComponent(hostId), { method: 'DELETE' });
            const data = await response.json();
            if (!response.ok || !data.success) {
                showModalError((data && data.error) || 'Gagal menghapus host');
                return;
            }
            if (currentHost === hostId) currentHost = '';
            await loadData();
        } catch (err) {
            showModalError('Gagal menghapus host');
        }
    }

    async function addHost(event) {
        event.preventDefault();
        showModalError('');
        if (typeof csrfFetch !== 'function') {
            showModalError('CSRF helper tidak tersedia');
            return;
        }
        const payload = {
            name: document.getElementById('imAddName').value.trim(),
            address: document.getElementById('imAddAddress').value.trim(),
            interval_seconds: parseInt(document.getElementById('imAddInterval').value, 10) || 20,
        };
        try {
            const response = await csrfFetch('/api/intensive/hosts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                showModalError((data && data.error) || 'Gagal menambah host');
                return;
            }
            addForm.reset();
            document.getElementById('imAddInterval').value = '20';
            if (data.host && data.host.id) currentHost = data.host.id;
            await loadData();
        } catch (err) {
            showModalError('Gagal menambah host');
        }
    }

    if (manageBtn) manageBtn.addEventListener('click', openModal);
    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modal) {
        modal.addEventListener('click', function (event) {
            if (event.target === modal) closeModal();
        });
    }
    if (addForm) addForm.addEventListener('submit', addHost);
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal && modal.classList.contains('show')) closeModal();
    });
})();
