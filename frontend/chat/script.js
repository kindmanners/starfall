const state = {me: null, users: [], selected: null, socket: null, retry: 0};
const peopleList = document.getElementById('peopleList');
const messages = document.getElementById('messages');
const messageInput = document.getElementById('messageInput');
const connectionStatus = document.getElementById('connectionStatus');

function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value ?? '';
    return element.innerHTML;
}

async function api(path, options = {}) {
    const response = await fetch(path, options);
    if (response.status === 401) {
        window.location.assign('/login');
        throw new Error('Session expired');
    }
    const result = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Request failed');
    return result;
}

function setConnection(label, online = false) {
    connectionStatus.textContent = label;
    connectionStatus.classList.toggle('online', online);
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function renderMessage(message) {
    if (document.querySelector(`[data-message-id="${message.id}"]`)) return;
    const own = Number(message.sender_id) === Number(state.me.id);
    const wrapper = document.createElement('div');
    wrapper.className = `message ${own ? 'own' : ''}`;
    wrapper.dataset.messageId = message.id;
    const file = message.has_file ? `
        <a class="file-card" href="${message.file_url}" download>
            <span class="file-icon">↧</span>
            <span><strong>${escapeHtml(message.file_name)}</strong><small>${formatSize(message.file_size || 0)}</small></span>
        </a>` : '';
    const text = message.content ? `<div class="message-bubble">${escapeHtml(message.content)}</div>` : '';
    const time = new Date(message.created_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    wrapper.innerHTML = `
        <div class="avatar">${escapeHtml((message.sender_name || '?')[0].toUpperCase())}</div>
        <div class="message-content">
            <div class="message-header"><span class="username">${own ? 'You' : escapeHtml(message.sender_name)}</span><span class="timestamp">${time}</span></div>
            ${text}${file}
        </div>`;
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
}

async function selectUser(user) {
    state.selected = user;
    document.querySelectorAll('.dm-item').forEach((node) => node.classList.toggle('active', Number(node.dataset.userId) === Number(user.id)));
    document.getElementById('welcomeView').classList.add('hidden');
    document.getElementById('chatView').classList.remove('hidden');
    document.getElementById('chatName').textContent = user.username;
    document.getElementById('chatAvatar').textContent = user.username[0].toUpperCase();
    messageInput.placeholder = `Message ${user.username}`;
    messages.innerHTML = '<div class="loading-message">Loading conversation…</div>';
    const result = await api(`/api/conversations/${user.id}`);
    messages.innerHTML = '';
    result.messages.forEach(renderMessage);
    messageInput.focus();
}

function renderUsers() {
    peopleList.innerHTML = '';
    document.getElementById('peopleEmpty').classList.toggle('hidden', state.users.length > 0);
    state.users.forEach((user) => {
        const item = document.createElement('button');
        item.className = 'dm-item';
        item.dataset.userId = user.id;
        item.innerHTML = `<span class="dm-avatar">${escapeHtml(user.username[0].toUpperCase())}</span><span class="dm-info"><span class="dm-name">${escapeHtml(user.username)}</span><span class="dm-status">Tap to chat</span></span>`;
        item.addEventListener('click', () => selectUser(user));
        peopleList.appendChild(item);
    });
}

function connect() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws`);
    state.socket = socket;
    socket.addEventListener('open', () => {
        state.retry = 0;
        setConnection('Online', true);
    });
    socket.addEventListener('message', (event) => {
        const message = JSON.parse(event.data);
        if (message.type === 'error') {
            alert(message.detail);
            return;
        }
        const belongsToOpenChat = state.selected && (
            Number(message.sender_id) === Number(state.selected.id) ||
            Number(message.recipient_id) === Number(state.selected.id)
        );
        if (belongsToOpenChat) renderMessage(message);
    });
    socket.addEventListener('close', (event) => {
        if (event.code === 4008) {
            window.location.assign('/login');
            return;
        }
        setConnection('Reconnecting…');
        const delay = Math.min(1000 * (2 ** state.retry), 15000);
        state.retry += 1;
        window.setTimeout(connect, delay);
    });
    socket.addEventListener('error', () => setConnection('Offline'));
}

document.getElementById('messageForm').addEventListener('submit', (event) => {
    event.preventDefault();
    const content = messageInput.value.trim();
    if (!content || !state.selected) return;
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
        alert('Still reconnecting. Try again in a moment.');
        return;
    }
    state.socket.send(JSON.stringify({recipient_id: Number(state.selected.id), content}));
    messageInput.value = '';
});

document.getElementById('attachmentButton').addEventListener('click', () => {
    if (!state.selected) return;
    document.getElementById('fileInput').click();
});

document.getElementById('fileInput').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    if (!file || !state.selected) return;
    const status = document.getElementById('uploadStatus');
    status.textContent = `Uploading ${file.name}…`;
    status.classList.remove('hidden');
    const data = new FormData();
    data.append('upload', file);
    try {
        await api(`/api/conversations/${state.selected.id}/files`, {method: 'POST', body: data});
        status.textContent = 'File shared.';
    } catch (error) {
        status.textContent = error.message;
    } finally {
        event.target.value = '';
        window.setTimeout(() => status.classList.add('hidden'), 2500);
    }
});

document.getElementById('logoutButton').addEventListener('click', async () => {
    await api('/api/logout', {method: 'POST'});
    window.location.assign('/login');
});

for (let i = 0; i < 24; i += 1) {
    const star = document.createElement('div');
    star.className = 'star';
    star.style.left = `${Math.random() * 100}%`;
    star.style.animationDelay = `${Math.random() * 5}s`;
    document.getElementById('starfallBg').appendChild(star);
}

(async function initialize() {
    const [me, users] = await Promise.all([api('/api/me'), api('/api/users')]);
    state.me = me.user;
    state.users = users.users;
    document.getElementById('myName').textContent = state.me.username;
    document.getElementById('myAvatar').textContent = state.me.username[0].toUpperCase();
    if (!state.users.length) document.getElementById('welcomeMessage').textContent = 'You’re ready. Ask your friend to sign up, then refresh this page.';
    renderUsers();
    connect();
})().catch((error) => console.error(error));
