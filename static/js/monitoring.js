function showMonitoringFetchErrors(errors) {
    const banner = document.getElementById('fetchErrorsBanner');
    if (!banner) return;
    if (!errors || !errors.length) {
        banner.hidden = true;
        banner.innerHTML = '';
        return;
    }

    const names = [];
    errors.forEach(function (msg) {
        const match = String(msg).match(/container\s+([^\s(]+)/i);
        if (match && names.indexOf(match[1]) === -1) {
            names.push(match[1]);
        }
    });
    const fromLabel = names.length ? names.join(', ') : 'one or more containers';

    const title = document.createElement('div');
    title.className = 'monitoring-fetch-alert-title';
    title.textContent = 'Warning: Data from ' + fromLabel + ' could not be retrieved. Displayed data is incomplete.';

    const list = document.createElement('ul');
    errors.forEach(function (msg) {
        const li = document.createElement('li');
        li.textContent = msg;
        list.appendChild(li);
    });

    banner.hidden = false;
    banner.replaceChildren(title, list);
}
