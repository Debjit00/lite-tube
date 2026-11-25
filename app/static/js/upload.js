/** Upload studio: file dropzone, client-side <canvas> thumbnail capture, and XHR upload progress. */

import { showToast } from "./api.js";

const uploadAuthGate = document.getElementById("uploadAuthGate");
const uploadSignInBtn = document.getElementById("uploadSignInBtn");
const uploadStudio = document.getElementById("uploadStudio");

const videoDropzone = document.getElementById("videoDropzone");
const videoFileInput = document.getElementById("videoFileInput");
const videoFileLabel = document.getElementById("videoFileLabel");
const previewBox = document.getElementById("previewBox");
const previewPlayer = document.getElementById("previewPlayer");
const thumbPreviewImg = document.getElementById("thumbPreviewImg");
const customThumbInput = document.getElementById("customThumbInput");
const resetThumbBtn = document.getElementById("resetThumbBtn");

const uploadError = document.getElementById("uploadError");
const videoTitleInput = document.getElementById("videoTitleInput");
const videoCategorySelect = document.getElementById("videoCategorySelect");
const videoTagsInput = document.getElementById("videoTagsInput");
const videoDescInput = document.getElementById("videoDescInput");
const uploadProgressWrap = document.getElementById("uploadProgressWrap");
const uploadProgressPct = document.getElementById("uploadProgressPct");
const uploadProgressBar = document.getElementById("uploadProgressBar");
const publishBtn = document.getElementById("publishBtn");

let selectedVideoFile = null;
let autoThumbBlob = null;
let customThumbFile = null;
let detectedDurationSeconds = 0;
let previewObjectUrl = null;
let thumbObjectUrl = null;

function syncAuthGate(user) {
    const signedIn = Boolean(user);
    uploadAuthGate.classList.toggle("hidden", signedIn);
    uploadStudio.classList.toggle("hidden", !signedIn);
}

uploadSignInBtn?.addEventListener("click", () => {
    window.LiteTubeAuth?.openModal("login");
});

window.addEventListener("litetube:auth-changed", (e) => {
    syncAuthGate(e.detail?.user || null);
});

function setThumbPreviewFromBlob(blob) {
    if (thumbObjectUrl) URL.revokeObjectURL(thumbObjectUrl);
    thumbObjectUrl = URL.createObjectURL(blob);
    thumbPreviewImg.src = thumbObjectUrl;
}

function captureThumbnailFromVideo(file) {
    if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = URL.createObjectURL(file);
    previewPlayer.src = previewObjectUrl;
    previewBox.classList.remove("hidden");

    const tempVideo = document.createElement("video");
    tempVideo.muted = true;
    tempVideo.playsInline = true;
    tempVideo.preload = "auto";
    tempVideo.src = previewObjectUrl;

    let captured = false;

    const drawCurrentFrame = () => {
        if (captured) return;
        captured = true;
        const canvas = document.createElement("canvas");
        canvas.width = 640;
        canvas.height = 360;
        const ctx = canvas.getContext("2d");
        if (ctx && tempVideo.videoWidth > 0 && tempVideo.videoHeight > 0) {
            ctx.fillStyle = "#000000";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            const scale = Math.min(
                canvas.width / tempVideo.videoWidth,
                canvas.height / tempVideo.videoHeight
            );
            const dw = tempVideo.videoWidth * scale;
            const dh = tempVideo.videoHeight * scale;
            ctx.drawImage(
                tempVideo,
                (canvas.width - dw) / 2,
                (canvas.height - dh) / 2,
                dw,
                dh
            );
            canvas.toBlob((blob) => {
                if (blob) {
                    autoThumbBlob = blob;
                    if (!customThumbFile) setThumbPreviewFromBlob(blob);
                }
            }, "image/png");
        }
    };

    tempVideo.addEventListener("loadedmetadata", () => {
        if (Number.isFinite(tempVideo.duration)) {
            detectedDurationSeconds = Math.max(0, Math.round(tempVideo.duration));
            const targetTime = tempVideo.duration > 0.5
                ? Math.min(1.2, tempVideo.duration * 0.25)
                : 0;
            tempVideo.currentTime = targetTime;
        }
    });

    tempVideo.addEventListener("seeked", drawCurrentFrame, { once: true });
    tempVideo.addEventListener("loadeddata", () => {
        setTimeout(drawCurrentFrame, 450);
    }, { once: true });
}

function handleVideoSelection(file) {
    if (!file) return;
    uploadError.classList.add("hidden");

    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".mp4") && !lower.endsWith(".webm")) {
        uploadError.textContent = "Please choose an .mp4 or .webm video file.";
        uploadError.classList.remove("hidden");
        return;
    }

    selectedVideoFile = file;
    autoThumbBlob = null;
    detectedDurationSeconds = 0;

    videoFileLabel.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    if (!videoTitleInput.value.trim()) {
        videoTitleInput.value = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    }

    publishBtn.disabled = false;
    captureThumbnailFromVideo(file);
}

videoDropzone?.addEventListener("click", () => videoFileInput?.click());
videoDropzone?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        videoFileInput?.click();
    }
});

videoDropzone?.addEventListener("dragover", (e) => {
    e.preventDefault();
    videoDropzone.classList.add("dragover");
});

videoDropzone?.addEventListener("dragleave", () => {
    videoDropzone.classList.remove("dragover");
});

videoDropzone?.addEventListener("drop", (e) => {
    e.preventDefault();
    videoDropzone.classList.remove("dragover");
    const file = e.dataTransfer?.files?.[0];
    handleVideoSelection(file);
});

videoFileInput?.addEventListener("change", () => {
    handleVideoSelection(videoFileInput.files?.[0]);
});

customThumbInput?.addEventListener("change", () => {
    const file = customThumbInput.files?.[0];
    if (!file) return;
    customThumbFile = file;
    setThumbPreviewFromBlob(file);
    resetThumbBtn.classList.remove("hidden");
});

resetThumbBtn?.addEventListener("click", () => {
    customThumbFile = null;
    customThumbInput.value = "";
    resetThumbBtn.classList.add("hidden");
    if (autoThumbBlob) setThumbPreviewFromBlob(autoThumbBlob);
});

uploadStudio?.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!selectedVideoFile) return;

    uploadError.classList.add("hidden");
    publishBtn.disabled = true;
    uploadProgressWrap.classList.remove("hidden");
    uploadProgressBar.style.width = "0%";
    uploadProgressPct.textContent = "0%";

    const formData = new FormData();
    formData.append("title", videoTitleInput.value.trim());
    formData.append("category", videoCategorySelect.value);
    formData.append("tags", videoTagsInput.value.trim());
    formData.append("description", videoDescInput.value.trim());
    formData.append("duration_seconds", String(detectedDurationSeconds));
    formData.append("video", selectedVideoFile);

    if (customThumbFile) {
        formData.append("thumbnail", customThumbFile);
    } else if (autoThumbBlob) {
        formData.append("thumbnail", autoThumbBlob, "thumbnail.png");
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/videos");
    xhr.withCredentials = true;

    xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const pct = Math.min(100, Math.round((event.loaded / event.total) * 100));
        uploadProgressBar.style.width = `${pct}%`;
        uploadProgressPct.textContent = `${pct}%`;
    };

    xhr.onload = () => {
        let payload = null;
        try {
            payload = JSON.parse(xhr.responseText);
        } catch {
            payload = null;
        }

        if (xhr.status >= 200 && xhr.status < 300 && payload?.video?.id) {
            showToast("Video published!");
            window.location.href = `/watch/${encodeURIComponent(payload.video.id)}`;
            return;
        }

        uploadError.textContent = payload?.detail || `Upload failed (${xhr.status})`;
        uploadError.classList.remove("hidden");
        publishBtn.disabled = false;
    };

    xhr.onerror = () => {
        uploadError.textContent = "Network error while uploading video.";
        uploadError.classList.remove("hidden");
        publishBtn.disabled = false;
    };

    xhr.send(formData);
});

(async () => {
    const user = await window.LiteTubeAuth?.ready;
    syncAuthGate(user || null);
})();
