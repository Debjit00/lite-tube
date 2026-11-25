/** Shared header navigation, sidebar drawer, search submission, and auth modal UI. */

import { apiFetch, escapeHtml, showToast } from "./api.js";

const authArea = document.getElementById("authArea");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const sidebarMyUploads = document.getElementById("sidebarMyUploads");

const headerSearchForm = document.getElementById("headerSearchForm");
const searchInput = document.getElementById("searchInput");
const searchClearBtn = document.getElementById("searchClearBtn");

const authModal = document.getElementById("authModal");
const authModalTitle = document.getElementById("authModalTitle");
const closeAuthModalBtn = document.getElementById("closeAuthModalBtn");
const tabLoginBtn = document.getElementById("tabLoginBtn");
const tabRegisterBtn = document.getElementById("tabRegisterBtn");
const authForm = document.getElementById("authForm");
const authError = document.getElementById("authError");
const authUsername = document.getElementById("authUsername");
const authDisplayNameGroup = document.getElementById("authDisplayNameGroup");
const authDisplayName = document.getElementById("authDisplayName");
const authPassword = document.getElementById("authPassword");
const authSubmitBtn = document.getElementById("authSubmitBtn");
const demoCredsHint = document.getElementById("demoCredsHint");
const fillDemoBtn = document.getElementById("fillDemoBtn");

let currentUser = null;
let authMode = "login";
let resolveReady;
const readyPromise = new Promise((resolve) => {
    resolveReady = resolve;
});

function emitAuthChanged() {
    window.dispatchEvent(
        new CustomEvent("litetube:auth-changed", { detail: { user: currentUser } })
    );
}

function setAuthMode(mode) {
    authMode = mode;
    const isRegister = mode === "register";
    tabLoginBtn.classList.toggle("active", !isRegister);
    tabRegisterBtn.classList.toggle("active", isRegister);
    authDisplayNameGroup.classList.toggle("hidden", !isRegister);
    demoCredsHint.classList.toggle("hidden", isRegister);
    authModalTitle.textContent = isRegister ? "Create your LiteTube channel" : "Sign in to LiteTube";
    authSubmitBtn.textContent = isRegister ? "Create account" : "Sign in";
    authError.classList.add("hidden");
}

function openAuthModal(mode = "login") {
    setAuthMode(mode);
    authModal.classList.remove("hidden");
    authUsername.focus();
}

function closeAuthModal() {
    authModal.classList.add("hidden");
    authError.classList.add("hidden");
}

function renderAuthHeader() {
    if (!currentUser) {
        sidebarMyUploads?.classList.add("hidden");
        authArea.innerHTML = `<button id="openSignInBtn" class="btn btn-outline-blue" type="button">Sign in</button>`;
        document.getElementById("openSignInBtn")?.addEventListener("click", () => openAuthModal("login"));
        return;
    }

    if (sidebarMyUploads) {
        sidebarMyUploads.href = `/?channel=${encodeURIComponent(currentUser.username)}`;
        sidebarMyUploads.classList.remove("hidden");
    }

    const initial = escapeHtml((currentUser.display_name || currentUser.username).charAt(0));
    const color = escapeHtml(currentUser.avatar_color || "#3b82f6");
    const displayName = escapeHtml(currentUser.display_name);
    const username = escapeHtml(currentUser.username);

    authArea.innerHTML = `
        <div class="user-menu-wrap">
            <button id="userMenuBtn" class="user-pill-btn" type="button" aria-expanded="false">
                <span class="avatar-circle" style="background: ${color};">${initial}</span>
                <span class="btn-label-hide-sm">${displayName}</span>
            </button>
            <div id="userDropdown" class="user-dropdown hidden">
                <div class="user-dropdown-header">
                    <div class="user-dropdown-name">${displayName}</div>
                    <div class="user-dropdown-handle">@${username}</div>
                </div>
                <a class="dropdown-item" href="/?channel=${encodeURIComponent(currentUser.username)}">My Uploads</a>
                <a class="dropdown-item" href="/upload">Upload Video</a>
                <button id="logoutBtn" class="dropdown-item" type="button">Sign out</button>
            </div>
        </div>
    `;

    const menuBtn = document.getElementById("userMenuBtn");
    const dropdown = document.getElementById("userDropdown");

    menuBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        const isHidden = dropdown.classList.toggle("hidden");
        menuBtn.setAttribute("aria-expanded", String(!isHidden));
    });

    document.getElementById("logoutBtn")?.addEventListener("click", async () => {
        await apiFetch("/api/auth/logout", { method: "POST" });
        currentUser = null;
        renderAuthHeader();
        emitAuthChanged();
        showToast("Signed out");
    });
}

document.addEventListener("click", () => {
    const dropdown = document.getElementById("userDropdown");
    if (dropdown && !dropdown.classList.contains("hidden")) {
        dropdown.classList.add("hidden");
    }
});

// Sidebar toggle for desktop & mobile
sidebarToggle?.addEventListener("click", () => {
    if (window.innerWidth <= 840) {
        document.body.classList.toggle("sidebar-open-mobile");
    } else {
        document.body.classList.toggle("sidebar-collapsed");
    }
});

sidebarBackdrop?.addEventListener("click", () => {
    document.body.classList.remove("sidebar-open-mobile");
});

// Search bar behavior
if (searchInput && searchClearBtn) {
    const params = new URLSearchParams(window.location.search);
    if (params.get("q")) {
        searchInput.value = params.get("q");
        searchClearBtn.classList.remove("hidden");
    }

    searchInput.addEventListener("input", () => {
        searchClearBtn.classList.toggle("hidden", !searchInput.value);
    });

    searchClearBtn.addEventListener("click", () => {
        searchInput.value = "";
        searchClearBtn.classList.add("hidden");
        if (window.location.pathname === "/") {
            searchInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        searchInput.focus();
    });
}

headerSearchForm?.addEventListener("submit", (e) => {
    if (window.location.pathname === "/") {
        return; // home.js handles live filtering
    }
    e.preventDefault();
    const query = (searchInput?.value || "").trim();
    const target = query ? `/?q=${encodeURIComponent(query)}` : "/";
    window.location.href = target;
});

// Auth modal listeners
closeAuthModalBtn?.addEventListener("click", closeAuthModal);
authModal?.addEventListener("click", (e) => {
    if (e.target === authModal) closeAuthModal();
});
tabLoginBtn?.addEventListener("click", () => setAuthMode("login"));
tabRegisterBtn?.addEventListener("click", () => setAuthMode("register"));

fillDemoBtn?.addEventListener("click", () => {
    authUsername.value = "techbytes";
    authPassword.value = "demo1234";
    authPassword.focus();
});

authForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    authError.classList.add("hidden");
    authSubmitBtn.disabled = true;

    try {
        const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
        const body =
            authMode === "register"
                ? {
                      username: authUsername.value.trim(),
                      display_name: authDisplayName.value.trim() || null,
                      password: authPassword.value,
                  }
                : {
                      username: authUsername.value.trim(),
                      password: authPassword.value,
                  };

        const data = await apiFetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        currentUser = data.user;
        authForm.reset();
        closeAuthModal();
        renderAuthHeader();
        emitAuthChanged();
        showToast(authMode === "register" ? "Channel created!" : `Welcome back, ${currentUser.display_name}`);
    } catch (err) {
        authError.textContent = err.message;
        authError.classList.remove("hidden");
    } finally {
        authSubmitBtn.disabled = false;
    }
});

window.LiteTubeAuth = {
    openModal: openAuthModal,
    getUser: () => currentUser,
    ready: readyPromise,
};

async function initAuth() {
    try {
        const data = await apiFetch("/api/auth/me");
        currentUser = data.user || null;
    } catch {
        currentUser = null;
    }
    renderAuthHeader();
    emitAuthChanged();
    resolveReady(currentUser);
}

initAuth();
