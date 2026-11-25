/** Watch page controller: HTML5 playback, play-triggered view count, Up Next sidebar, owner deletion. */

import {
    apiFetch,
    escapeHtml,
    formatBytes,
    formatDuration,
    formatViews,
    showToast,
    timeAgo,
} from "./api.js";

const watchRoot = document.getElementById("watchRoot");
const watchNotFound = document.getElementById("watchNotFound");
const videoId = watchRoot?.dataset.videoId || "";

const videoPlayer = document.getElementById("videoPlayer");
const watchTitle = document.getElementById("watchTitle");
const watchChannelAvatarLink = document.getElementById("watchChannelAvatarLink");
const watchChannelAvatar = document.getElementById("watchChannelAvatar");
const watchChannelName = document.getElementById("watchChannelName");
const watchChannelHandle = document.getElementById("watchChannelHandle");
const watchViews = document.getElementById("watchViews");
const watchCategoryPill = document.getElementById("watchCategoryPill");
const deleteVideoBtn = document.getElementById("deleteVideoBtn");
const watchCreated = document.getElementById("watchCreated");
const watchFileSize = document.getElementById("watchFileSize");
const watchDescription = document.getElementById("watchDescription");
const watchTags = document.getElementById("watchTags");
const relatedList = document.getElementById("relatedList");

let loadedVideo = null;
let viewRecorded = false;

function updateOwnerDeleteButton(user) {
    if (!loadedVideo || !deleteVideoBtn) return;
    const isOwner = Boolean(user && user.id === loadedVideo.channel.id);
    deleteVideoBtn.classList.toggle("hidden", !isOwner);
}

function renderRelated(related) {
    if (!related || related.length === 0) {
        relatedList.innerHTML = `<p style="color: var(--text-secondary);">No related videos yet.</p>`;
        return;
    }

    relatedList.innerHTML = related
        .map((v) => {
            const href = `/watch/${encodeURIComponent(v.id)}`;
            const title = escapeHtml(v.title);
            const channelName = escapeHtml(v.channel.display_name);
            return `
                <a class="related-card" href="${href}">
                    <div class="thumb-wrap">
                        <img class="thumb-img" src="${escapeHtml(v.thumbnail_url)}" alt="${title}" loading="lazy" />
                        <span class="duration-badge">${formatDuration(v.duration_seconds)}</span>
                    </div>
                    <div class="video-meta-text">
                        <h3 class="video-title">${title}</h3>
                        <div class="video-channel-link">${channelName}</div>
                        <div class="video-stats">${formatViews(v.views)} &bull; ${timeAgo(v.created_at)}</div>
                    </div>
                </a>
            `;
        })
        .join("");
}

async function initWatchPage() {
    try {
        const data = await apiFetch(`/api/videos/${encodeURIComponent(videoId)}`);
        loadedVideo = data.video;

        document.title = `${loadedVideo.title} — LiteTube`;
        videoPlayer.src = loadedVideo.stream_url;
        videoPlayer.poster = loadedVideo.thumbnail_url;

        watchTitle.textContent = loadedVideo.title;
        const channelUrl = `/?channel=${encodeURIComponent(loadedVideo.channel.username)}`;
        watchChannelAvatarLink.href = channelUrl;
        watchChannelName.href = channelUrl;
        watchChannelName.textContent = loadedVideo.channel.display_name;
        watchChannelHandle.textContent = `@${loadedVideo.channel.username}`;
        watchChannelAvatar.textContent = (
            loadedVideo.channel.display_name || loadedVideo.channel.username
        ).charAt(0);
        watchChannelAvatar.style.background = loadedVideo.channel.avatar_color || "#3b82f6";

        watchViews.textContent = formatViews(loadedVideo.views);
        watchCategoryPill.textContent = loadedVideo.category;
        watchCreated.textContent = new Date(loadedVideo.created_at).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
        });
        watchFileSize.textContent = formatBytes(loadedVideo.file_size);
        watchDescription.textContent =
            loadedVideo.description || "No description provided.";

        watchTags.innerHTML = (loadedVideo.tags || [])
            .map(
                (tag) =>
                    `<a class="tag-pill" href="/?q=${encodeURIComponent(tag)}">#${escapeHtml(tag)}</a>`
            )
            .join("");

        renderRelated(data.related);

        await window.LiteTubeAuth?.ready;
        updateOwnerDeleteButton(window.LiteTubeAuth?.getUser());
    } catch (err) {
        watchRoot.classList.add("hidden");
        watchNotFound.classList.remove("hidden");
    }
}

videoPlayer?.addEventListener("play", async () => {
    if (viewRecorded || !loadedVideo) return;
    viewRecorded = true;
    try {
        const res = await apiFetch(`/api/videos/${encodeURIComponent(loadedVideo.id)}/view`, {
            method: "POST",
        });
        watchViews.textContent = formatViews(res.views);
    } catch {
        // Non-critical if view increment fails transiently
    }
});

deleteVideoBtn?.addEventListener("click", async () => {
    if (!loadedVideo) return;
    if (!window.confirm(`Delete "${loadedVideo.title}"? This cannot be undone.`)) {
        return;
    }
    deleteVideoBtn.disabled = true;
    try {
        await apiFetch(`/api/videos/${encodeURIComponent(loadedVideo.id)}`, {
            method: "DELETE",
        });
        showToast("Video deleted");
        window.location.href = "/";
    } catch (err) {
        showToast(err.message, true);
        deleteVideoBtn.disabled = false;
    }
});

window.addEventListener("litetube:auth-changed", (e) => {
    updateOwnerDeleteButton(e.detail?.user || null);
});

initWatchPage();
