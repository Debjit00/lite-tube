/** Home feed controller: search, category chips, channel filter, sorting, and grid rendering. */

import {
    apiFetch,
    escapeHtml,
    formatDuration,
    formatViews,
    timeAgo,
} from "./api.js";

const videoGrid = document.getElementById("videoGrid");
const emptyState = document.getElementById("emptyState");
const categoryChips = document.getElementById("categoryChips");
const sortSelect = document.getElementById("sortSelect");
const activeFilterBanner = document.getElementById("activeFilterBanner");
const activeFilterText = document.getElementById("activeFilterText");
const clearFiltersBtn = document.getElementById("clearFiltersBtn");

const headerSearchForm = document.getElementById("headerSearchForm");
const searchInput = document.getElementById("searchInput");
const searchClearBtn = document.getElementById("searchClearBtn");

const state = {
    q: "",
    category: "All",
    channel: "",
    sort: "newest",
};

function readUrlState() {
    const params = new URLSearchParams(window.location.search);
    state.q = params.get("q") || "";
    state.category = params.get("category") || "All";
    state.channel = params.get("channel") || "";
    state.sort = params.get("sort") === "views" ? "views" : "newest";

    if (searchInput) searchInput.value = state.q;
    if (searchClearBtn) searchClearBtn.classList.toggle("hidden", !state.q);
    if (sortSelect) sortSelect.value = state.sort;
}

function syncUrlState() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.category && state.category !== "All") params.set("category", state.category);
    if (state.channel) params.set("channel", state.channel);
    if (state.sort && state.sort !== "newest") params.set("sort", state.sort);

    const qs = params.toString();
    const newUrl = qs ? `/?${qs}` : "/";
    window.history.replaceState(null, "", newUrl);
}

function updateActiveControls() {
    categoryChips?.querySelectorAll(".chip").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.category === state.category);
    });

    document.querySelectorAll("[data-sidebar-category]").forEach((link) => {
        link.classList.toggle(
            "active",
            link.dataset.sidebarCategory === state.category &&
                state.category !== "All" &&
                !state.channel &&
                state.sort === "newest"
        );
    });

    const navHome = document.querySelector('[data-nav="home"]');
    const navTrending = document.querySelector('[data-nav="trending"]');
    const navMyUploads = document.getElementById("sidebarMyUploads");
    const currentUser = window.LiteTubeAuth?.getUser();
    const isMyUploads = Boolean(currentUser && state.channel === currentUser.username);

    navHome?.classList.toggle(
        "active",
        state.category === "All" && !state.channel && state.sort === "newest"
    );
    navTrending?.classList.toggle("active", state.sort === "views" && !state.channel);
    navMyUploads?.classList.toggle("active", isMyUploads);

    const parts = [];
    if (state.q) parts.push(`Search: "${state.q}"`);
    if (state.category !== "All") parts.push(`Category: ${state.category}`);
    if (state.channel) parts.push(`Channel: @${state.channel}`);

    if (parts.length > 0) {
        activeFilterText.textContent = parts.join(" • ");
        activeFilterBanner.classList.remove("hidden");
    } else {
        activeFilterBanner.classList.add("hidden");
    }
}

function renderVideos(videos) {
    if (!videos || videos.length === 0) {
        videoGrid.innerHTML = "";
        emptyState.classList.remove("hidden");
        return;
    }

    emptyState.classList.add("hidden");
    videoGrid.innerHTML = videos
        .map((v) => {
            const title = escapeHtml(v.title);
            const thumbUrl = escapeHtml(v.thumbnail_url);
            const watchHref = `/watch/${encodeURIComponent(v.id)}`;
            const channelHref = `/?channel=${encodeURIComponent(v.channel.username)}`;
            const channelName = escapeHtml(v.channel.display_name);
            const initial = escapeHtml((v.channel.display_name || v.channel.username).charAt(0));
            const color = escapeHtml(v.channel.avatar_color || "#3b82f6");

            return `
                <article class="video-card">
                    <a class="thumb-wrap" href="${watchHref}">
                        <img class="thumb-img" src="${thumbUrl}" alt="${title}" loading="lazy" />
                        <span class="duration-badge">${formatDuration(v.duration_seconds)}</span>
                    </a>
                    <div class="video-meta-row">
                        <a href="${channelHref}" title="${channelName}">
                            <span class="avatar-circle" style="background: ${color};">${initial}</span>
                        </a>
                        <div class="video-meta-text">
                            <a href="${watchHref}">
                                <h3 class="video-title">${title}</h3>
                            </a>
                            <a class="video-channel-link" href="${channelHref}">${channelName}</a>
                            <div class="video-stats">${formatViews(v.views)} &bull; ${timeAgo(v.created_at)}</div>
                        </div>
                    </div>
                </article>
            `;
        })
        .join("");
}

async function loadFeed() {
    updateActiveControls();
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.category && state.category !== "All") params.set("category", state.category);
    if (state.channel) params.set("channel", state.channel);
    params.set("sort", state.sort);

    const data = await apiFetch(`/api/videos?${params.toString()}`);
    renderVideos(data.videos);
}

categoryChips?.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.category = chip.dataset.category || "All";
    syncUrlState();
    loadFeed();
});

sortSelect?.addEventListener("change", () => {
    state.sort = sortSelect.value;
    syncUrlState();
    loadFeed();
});

clearFiltersBtn?.addEventListener("click", () => {
    state.q = "";
    state.category = "All";
    state.channel = "";
    state.sort = "newest";
    if (searchInput) searchInput.value = "";
    if (searchClearBtn) searchClearBtn.classList.add("hidden");
    if (sortSelect) sortSelect.value = "newest";
    syncUrlState();
    loadFeed();
});

let searchDebounce = null;
searchInput?.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
        state.q = searchInput.value.trim();
        syncUrlState();
        loadFeed();
    }, 220);
});

headerSearchForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    clearTimeout(searchDebounce);
    state.q = (searchInput?.value || "").trim();
    syncUrlState();
    loadFeed();
});

window.addEventListener("litetube:auth-changed", () => {
    updateActiveControls();
});

readUrlState();
loadFeed();
