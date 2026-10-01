const starsContainer = document.getElementById('stars');
for (let i = 0; i < 100; i += 1) {
    const star = document.createElement('div');
    star.className = 'star';
    star.style.left = `${Math.random() * 100}%`;
    star.style.top = `${Math.random() * 100}%`;
    star.style.animationDelay = `${Math.random() * 4}s`;
    starsContainer.appendChild(star);
}

function messageFrom(result, fallback) {
    if (typeof result?.detail === 'string') return result.detail;
    if (Array.isArray(result?.detail)) return result.detail[0]?.msg || fallback;
    return fallback;
}

async function submitAuth(path, payload, button) {
    const oldLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Please wait…';
    try {
        const response = await fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(messageFrom(result, 'Something went wrong'));
        window.location.assign('/chat');
    } catch (error) {
        alert(error.message);
    } finally {
        button.disabled = false;
        button.textContent = oldLabel;
    }
}

document.getElementById('loginFormElement').addEventListener('submit', (event) => {
    event.preventDefault();
    submitAuth('/api/login', {
        email: document.getElementById('loginEmail').value.trim(),
        password: document.getElementById('loginPassword').value,
    }, event.submitter);
});

document.getElementById('signupFormElement').addEventListener('submit', (event) => {
    event.preventDefault();
    const password = document.getElementById('signupPassword').value;
    if (password !== document.getElementById('signupPasswordConfirm').value) {
        alert('Passwords do not match.');
        return;
    }
    submitAuth('/api/signup', {
        username: document.getElementById('signupName').value.trim(),
        email: document.getElementById('signupEmail').value.trim(),
        password,
    }, event.submitter);
});

document.getElementById('showSignup').addEventListener('click', (event) => {
    event.preventDefault();
    document.getElementById('loginForm').classList.remove('active');
    document.getElementById('signupForm').classList.add('active');
});

document.getElementById('showLogin').addEventListener('click', (event) => {
    event.preventDefault();
    document.getElementById('signupForm').classList.remove('active');
    document.getElementById('loginForm').classList.add('active');
});

fetch('/api/me').then((response) => {
    if (response.ok) window.location.assign('/chat');
});
