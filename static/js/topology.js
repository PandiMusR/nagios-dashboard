(() => {
    'use strict';

    const root = document.getElementById('topology');
    const control = name => document.getElementById('topology-' + name);
    const canvas = control('canvas');
    const edit = control('edit');
    const dialog = control('confirm');
    const style = () => getComputedStyle(root);
    const palette = () => {
        const declaration = style();
        return Object.fromEntries(['surface', 'text', 'muted', 'accent', 'up', 'down', 'unreachable', 'pending', 'unknown']
            .map(name => [name, declaration.getPropertyValue('--topo-' + name).trim()]));
    };
    let graph;
    let network;
    let nodeData;
    let edgeData;
    let hosts = new Map();
    let children = new Map();
    let original = new Map();
    let draft = new Map();
    let undo = [];
    let redo = [];
    let changed = new Set();
    let snapshot = {hosts: {}, stale: true};
    let selected = null;
    let horizontal = false;
    let editing = false;
    let saving = false;
    let conflicted = false;
    let generation = 0;
    const moved = new Map();

    const message = text => { control('message').textContent = text; };

    async function json(url, options) {
        const response = await fetch(url, {...options, cache: 'no-store'});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw Object.assign(new Error(data.error || 'The dashboard could not complete this request.'), {
                status: response.status
            });
        }
        return data;
    }

    function hostStatus(name) {
        return Object.hasOwn(snapshot.hosts, name) ? snapshot.hosts[name] : 'UNKNOWN';
    }

    function nodeAppearance(name, colors) {
        const state = colors[hostStatus(name).toLowerCase()];
        return {
            color: {
                background: colors.surface, border: state,
                highlight: {background: colors.surface, border: colors.accent},
                hover: {background: colors.surface, border: colors.accent}
            },
            font: {color: colors.text}
        };
    }

    function positions() {
        const groups = new Map();
        for (const node of graph.nodes) {
            if (!groups.has(node.level)) groups.set(node.level, []);
            groups.get(node.level).push(node);
        }
        const placed = [];
        for (const [level, members] of groups) {
            members.forEach((node, index) => {
                const across = (index - (members.length - 1) / 2) * 230;
                placed.push({id: hosts.get(node.id).index, x: horizontal ? level * 260 : across,
                    y: horizontal ? across : level * 125});
            });
        }
        return placed;
    }

    function refreshEdges() {
        children = new Map();
        const colors = palette();
        const updates = [];
        for (const [child, list] of draft) {
            const before = original.get(child);
            const names = new Set([...before, ...list]);
            for (const parent of names) {
                if (!hosts.has(parent)) continue;
                const removed = !list.includes(parent);
                const added = !before.includes(parent);
                if (!removed) {
                    if (!children.has(parent)) children.set(parent, []);
                    children.get(parent).push(child);
                }
                const related = selected === child || selected === parent;
                const from = hosts.get(parent).index;
                const to = hosts.get(child).index;
                updates.push({id: from + ':' + to, from, to, dashes: added || removed, width: related ? 3 : 1.4,
                    color: {color: colors[removed ? 'down' : added ? 'up' : related ? 'accent' : 'muted'], inherit: false}});
            }
        }
        const ids = new Set(updates.map(edge => edge.id));
        edgeData.remove(edgeData.getIds().filter(id => !ids.has(id)));
        edgeData.update(updates);
    }

    function setSnapshot(data) {
        snapshot = data;
        const label = data.last_success ? 'Last successful poll ' + data.last_success.replace('T', ' ') : 'No successful snapshot yet';
        control('snapshot').textContent = label + (data.stale && data.last_success ? ' · Stale or degraded' : '');
        if (!network) return;
        const colors = palette();
        nodeData.update(graph.nodes.map(node => {
            const id = hosts.get(node.id).index;
            return {id, ...network.getPosition(id), ...nodeAppearance(node.id, colors)};
        }));
        if (selected !== null) control('host-status').textContent = hostStatus(selected);
    }

    function mountGraph(data) {
        graph = data;
        hosts = new Map(data.nodes.map((node, index) => [node.id, {...node, index}]));
        original = new Map(data.nodes.map(node => [node.id, node.parents]));
        draft = new Map(original);
        changed = new Set();
        undo = [];
        redo = [];
        conflicted = false;
        snapshot = data.snapshot;
        if (network) network.destroy();
        const colors = palette();
        nodeData = new vis.DataSet(positions().map(({id, ...position}) => {
            const node = data.nodes[id];
            const label = node.id.length > 24 ? node.id.slice(0, 23) + '…' : node.id;
            return {id, label, ...(moved.get(node.id) || position), ...nodeAppearance(node.id, colors)};
        }));
        edgeData = new vis.DataSet();
        refreshEdges();
        network = new vis.Network(canvas, {nodes: nodeData, edges: edgeData}, {
            physics: false, layout: {improvedLayout: false},
            interaction: {hover: true, multiselect: false, selectConnectedEdges: false},
            nodes: {shape: 'box', margin: 10, borderWidth: 2, borderWidthSelected: 4},
            edges: {arrows: 'to', smooth: {enabled: true, type: 'cubicBezier', roundness: 0.25}}
        });
        network.on('dragEnd', event => {
            for (const id of event.nodes) moved.set(graph.nodes[id].id, network.getPosition(id));
        });
        network.on('selectNode', event => select(graph.nodes[event.nodes[0]].id, false));
        network.on('deselectNode', () => select(null, false));
        network.fit({animation: false});
        setSnapshot(data.snapshot);
        if (edit) edit.disabled = !data.can_edit || !data.nodes.length;
        message(data.warnings.join(' ') || (data.nodes.length ? 'Drag nodes to arrange this view. Arrows point from parent to child.' : 'No hosts are defined in localhost.cfg.'));
        if (!hosts.has(selected)) selected = null;
        select(selected, false);
        const search = control('search');
        search.dispatchEvent(new Event('input'));
    }

    function button(label, action, aria) {
        const element = document.createElement('button');
        element.type = 'button';
        element.textContent = label;
        if (aria) element.setAttribute('aria-label', aria);
        element.addEventListener('click', action);
        return element;
    }

    function relation(list, name, remove) {
        const item = document.createElement('li');
        if (hosts.has(name)) item.append(button(name, () => select(name, true)));
        else {
            const label = document.createElement('span');
            label.textContent = name + ' (outside this file)';
            item.append(label);
        }
        if (remove) item.append(button('Remove', remove, 'Remove parent ' + name));
        list.append(item);
    }

    function renderDetails() {
        const node = hosts.get(selected);
        control('host').textContent = node ? node.id : 'Host details';
        control('address').textContent = node ? [node.label !== node.id ? node.label : '', node.address].filter(Boolean).join(' · ') : '';
        control('host-status').textContent = node ? hostStatus(node.id) : 'Select a node or find a host.';
        control('parents').replaceChildren();
        control('children').replaceChildren();
        const candidate = control('candidate');
        candidate.replaceChildren();
        if (node) {
            for (const name of draft.get(node.id)) {
                relation(control('parents'), name, editing && !saving ? () => {
                    change(node.id, draft.get(node.id).filter(value => value !== name));
                } : null);
            }
            for (const name of children.get(node.id) || []) relation(control('children'), name);
            if (editing) {
                const skip = new Set([node.id, ...draft.get(node.id)]);
                for (const name of hosts.keys()) {
                    if (!skip.has(name)) candidate.add(new Option(name, name));
                }
            }
        }
        candidate.disabled = saving || !candidate.length;
        control('add').disabled = candidate.disabled;
        control('undo').disabled = saving || !undo.length;
        control('redo').disabled = saving || !redo.length;
        control('cancel').disabled = saving;
        control('update').disabled = saving || conflicted || !changed.size;
        control('draft').textContent = conflicted ? 'Cancel this draft to load the current topology before retrying.' :
            changed.size ? changed.size + ' host(s) changed · dashed green adds, dashed red removals' : 'No pending changes';
    }

    function select(name, center) {
        selected = name;
        if (name !== null) {
            const id = hosts.get(name).index;
            network.selectNodes([id], false);
            if (center) network.focus(id, {scale: Math.max(0.8, network.getScale()), animation: true});
        } else network.unselectAll();
        refreshEdges();
        renderDetails();
    }

    function applyDraft(name, list) {
        draft.set(name, list);
        const before = original.get(name);
        if (before.length === list.length && before.every(parent => list.includes(parent))) changed.delete(name);
        else changed.add(name);
        refreshEdges();
        renderDetails();
    }

    function change(name, list) {
        if (!editing || saving) return;
        undo.push({name, before: draft.get(name), after: list});
        redo = [];
        applyDraft(name, list);
    }

    function setEditing(value) {
        editing = value;
        control('editor').hidden = !value;
        edit.disabled = value || !graph.can_edit;
        renderDetails();
    }

    async function load() {
        const requestGeneration = ++generation;
        const data = await json(root.dataset.graph);
        if (requestGeneration === generation) mountGraph(data);
    }

    control('search').addEventListener('input', event => {
        const query = event.target.value.trim().toLowerCase();
        const result = control('results');
        result.replaceChildren();
        result.hidden = !query;
        if (!query) return;
        const matches = [...hosts.values()].filter(node => [node.id, node.label, node.address]
            .some(value => value.toLowerCase().includes(query))).slice(0, 10);
        for (const node of matches) result.append(button(node.id, () => select(node.id, true)));
        if (!matches.length) result.textContent = 'No matching hosts.';
    });

    for (const [action, multiplier] of [['in', 1.25], ['out', 0.8]]) {
        control(action).onclick = () => network?.moveTo({scale: Math.max(0.02, Math.min(4, network.getScale() * multiplier))});
    }
    control('fit').onclick = () => network?.fit({animation: false});
    control('reset').onclick = () => {
        if (!network) return;
        moved.clear();
        for (const position of positions()) network.moveNode(position.id, position.x, position.y);
        network.fit({animation: false});
    };
    control('direction').onclick = event => {
        horizontal = !horizontal;
        event.currentTarget.setAttribute('aria-pressed', String(horizontal));
        control('reset').click();
    };
    const map = canvas.closest('.topology-map');
    if (!map.requestFullscreen || !document.fullscreenEnabled) control('expand').hidden = true;
    control('expand').onclick = async () => {
        try {
            if (document.fullscreenElement === map) await document.exitFullscreen();
            else await map.requestFullscreen();
        } catch {
            message('Fullscreen is unavailable.');
        }
    };
    document.addEventListener('fullscreenchange', () => {
        const expanded = document.fullscreenElement === map;
        control('expand').textContent = expanded ? 'Exit fullscreen' : 'Expand';
        control('expand').setAttribute('aria-pressed', String(expanded));
        requestAnimationFrame(() => network?.fit({animation: false}));
    });

    if (edit) edit.onclick = () => setEditing(true);
    control('add').onclick = () => {
        const parent = control('candidate').value;
        if (selected !== null && parent) change(selected, [...draft.get(selected), parent]);
    };
    control('undo').onclick = () => {
        const entry = undo.pop();
        if (entry) { redo.push(entry); applyDraft(entry.name, entry.before); }
    };
    control('redo').onclick = () => {
        const entry = redo.pop();
        if (entry) { undo.push(entry); applyDraft(entry.name, entry.after); }
    };
    control('cancel').onclick = async () => {
        draft = new Map(original);
        changed = new Set();
        undo = [];
        redo = [];
        setEditing(false);
        refreshEdges();
        renderDetails();
        if (conflicted) {
            try { await load(); }
            catch (error) { message(error.message); edit.disabled = true; }
        }
    };
    control('update').onclick = () => {
        const summary = control('summary');
        summary.replaceChildren();
        for (const name of changed) {
            const item = document.createElement('li');
            item.textContent = name + ' · ' + (original.get(name).join(', ') || 'No parents') +
                ' → ' + (draft.get(name).join(', ') || 'No parents');
            summary.append(item);
        }
        dialog.showModal();
    };
    control('back').onclick = () => dialog.close();
    dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
    control('submit').onclick = async () => {
        if (saving || conflicted) return;
        saving = true;
        control('submit').disabled = true;
        control('back').disabled = true;
        renderDetails();
        let committed = false;
        try {
            const changes = Object.fromEntries([...changed].map(name => [name, draft.get(name)]));
            const result = await json(root.dataset.save, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content},
                body: JSON.stringify({revision: graph.revision, changes})
            });
            if (result?.success !== true || typeof result.changed !== 'boolean') {
                throw new Error('The dashboard did not confirm the update. Reload the topology before retrying.');
            }
            committed = true;
            dialog.close();
            setEditing(false);
            await load();
            message('Topology updated.');
        } catch (error) {
            if (!committed && (error.status === 409 || !error.status)) conflicted = true;
            dialog.close();
            if (committed) edit.disabled = true;
            message(committed ? 'Changes applied. Reload the page to see the current topology.' : error.message);
        } finally {
            saving = false;
            control('submit').disabled = false;
            control('back').disabled = false;
            renderDetails();
        }
    };

    async function poll() {
        const requestGeneration = generation;
        try {
            if (network && !document.hidden && !saving) {
                const data = await json(root.dataset.status);
                if (requestGeneration === generation) setSnapshot(data);
            }
        } catch {
            control('snapshot').textContent = 'Status refresh failed · showing last received values';
        } finally {
            setTimeout(poll, 30000);
        }
    }
    new MutationObserver(() => {
        if (network) { setSnapshot(snapshot); refreshEdges(); }
    }).observe(document.documentElement, {attributeFilter: ['data-theme']});
    load().catch(error => message(error.message));
    setTimeout(poll, 30000);
})();
