// ClipStream Client-Side Application Logic

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("extract-form");
  const urlInput = document.getElementById("video-url");
  const clearBtn = document.getElementById("clear-btn");
  const pasteBtn = document.getElementById("paste-btn");
  const submitBtn = document.getElementById("submit-btn");
  const btnText = submitBtn.querySelector(".btn-text");
  const btnSpinner = submitBtn.querySelector(".btn-spinner");
  const arrowIcon = submitBtn.querySelector(".arrow-icon");

  const errorCard = document.getElementById("error-card");
  const errorMessage = document.getElementById("error-message");

  const resultSection = document.getElementById("result-section");
  const videoThumbnail = document.getElementById("video-thumbnail");
  const videoDuration = document.getElementById("video-duration");
  const videoPlatform = document.getElementById("video-platform");
  const videoTitle = document.getElementById("video-title");
  const videoAuthor = document.getElementById("video-author");
  const videoViews = document.getElementById("video-views");

  const videoFormatList = document.getElementById("video-format-list");
  const audioFormatList = document.getElementById("audio-format-list");
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  const progressContainer = document.getElementById("download-progress-container");
  const progressStatusText = document.getElementById("progress-status-text");
  const progressPercent = document.getElementById("progress-percent");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressSpeed = document.getElementById("progress-speed");
  const progressEta = document.getElementById("progress-eta");
  const progressDownloadReady = document.getElementById("progress-download-ready");
  const directDownloadAnchor = document.getElementById("direct-download-anchor");

  let currentVideoUrl = "";
  let activePollInterval = null;

  // Toggle clear button
  urlInput.addEventListener("input", () => {
    clearBtn.style.display = urlInput.value ? "flex" : "none";
  });

  clearBtn.addEventListener("click", () => {
    urlInput.value = "";
    clearBtn.style.display = "none";
    urlInput.focus();
  });

  // Paste from clipboard
  pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        urlInput.value = text.trim();
        clearBtn.style.display = "flex";
        urlInput.focus();
      }
    } catch (err) {
      console.warn("Clipboard access denied or unsupported", err);
      urlInput.focus();
    }
  });

  // Sample pill click
  document.querySelectorAll(".sample-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      const sampleUrl = pill.getAttribute("data-url");
      if (sampleUrl) {
        urlInput.value = sampleUrl;
        clearBtn.style.display = "flex";
        form.dispatchEvent(new Event("submit"));
      }
    });
  });

  // Tabs switching
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      document.getElementById(targetId).classList.add("active");
    });
  });

  function showError(msg) {
    errorMessage.textContent = msg || "An unknown error occurred.";
    errorCard.style.display = "flex";
    errorCard.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function hideError() {
    errorCard.style.display = "none";
  }

  function setLoading(isLoading) {
    if (isLoading) {
      submitBtn.disabled = true;
      btnText.style.display = "none";
      arrowIcon.style.display = "none";
      btnSpinner.style.display = "inline-block";
    } else {
      submitBtn.disabled = false;
      btnText.style.display = "inline-block";
      arrowIcon.style.display = "inline-block";
      btnSpinner.style.display = "none";
    }
  }

  // Handle URL extraction
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();
    const url = urlInput.value.trim();
    if (!url) return;

    currentVideoUrl = url;
    setLoading(true);
    resultSection.style.display = "none";
    progressContainer.style.display = "none";
    if (activePollInterval) clearInterval(activePollInterval);

    try {
      const response = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        showError(data.error || "Failed to fetch video details.");
        return;
      }

      // Populate preview data
      videoTitle.textContent = data.title;
      videoAuthor.textContent = `👤 ${data.uploader || 'Creator'}`;
      videoViews.textContent = data.views ? `👁️ ${data.views} views` : `👁️ Active stream`;
      videoDuration.textContent = data.duration || "00:00";
      videoPlatform.textContent = data.platform || "Video";

      // Fallback thumbnail if none provided
      if (data.thumbnail) {
        videoThumbnail.src = data.thumbnail;
      } else {
        videoThumbnail.src = "data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%22640%22%20height%3D%22360%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Crect%20fill%3D%22%23161928%22%20width%3D%22640%22%20height%3D%22360%22%2F%3E%3Ctext%20fill%3D%22%236366f1%22%20font-family%3D%22sans-serif%22%20font-size%3D%2230%22%20font-weight%3D%22bold%22%20x%3D%2250%25%22%20y%3D%2250%25%22%20text-anchor%3D%22middle%22%3E%E2%96%B6%20Video%20Preview%3C%2Ftext%3E%3C%2Fsvg%3E";
      }

      // Render Video Formats
      videoFormatList.innerHTML = "";
      if (data.video_options && data.video_options.length > 0) {
        data.video_options.forEach((opt, index) => {
          const row = document.createElement("div");
          row.className = "format-row";
          const isHighRes = opt.height >= 1080;

          row.innerHTML = `
            <div class="format-info">
              <span class="format-badge ${isHighRes ? 'gold' : ''}">${opt.resolution}</span>
              <div class="format-details">
                <span class="format-name">${opt.label}</span>
                <span class="format-size">Format: .${opt.ext} • ${opt.filesize_str}</span>
              </div>
            </div>
            <button class="btn-download-action" data-type="video" data-resolution="${opt.resolution}" data-ext="${opt.ext}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>Download</span>
            </button>
          `;
          videoFormatList.appendChild(row);
        });
      }

      // Render Audio Formats
      audioFormatList.innerHTML = "";
      (data.audio_options || []).forEach(opt => {
        const row = document.createElement("div");
        row.className = "format-row";
        row.innerHTML = `
          <div class="format-info">
            <span class="format-badge">${opt.ext.toUpperCase()}</span>
            <div class="format-details">
              <span class="format-name">${opt.label}</span>
              <span class="format-size">Bitrate: ${opt.bitrate}</span>
            </div>
          </div>
          <button class="btn-download-action" data-type="audio" data-resolution="audio" data-ext="${opt.ext}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>Download</span>
          </button>
        `;
        audioFormatList.appendChild(row);
      });

      // Show result section
      resultSection.style.display = "block";
      resultSection.scrollIntoView({ behavior: "smooth", block: "start" });

      // Attach download triggers
      attachDownloadEvents();

    } catch (err) {
      showError("Connection failed. Please ensure the server is running and try again.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  });

  function attachDownloadEvents() {
    document.querySelectorAll(".btn-download-action").forEach(btn => {
      btn.addEventListener("click", () => {
        const type = btn.getAttribute("data-type");
        const resolution = btn.getAttribute("data-resolution");
        const ext = btn.getAttribute("data-ext");
        startDownloadTask(currentVideoUrl, type, resolution, ext);
      });
    });
  }

  async function startDownloadTask(url, type, resolution, ext) {
    hideError();
    progressContainer.style.display = "block";
    progressDownloadReady.style.display = "none";
    progressStatusText.textContent = "Initiating download...";
    progressPercent.textContent = "0%";
    progressBarFill.style.width = "0%";
    progressSpeed.textContent = "Connecting to source...";
    progressEta.textContent = "Estimated time: calculating...";

    progressContainer.scrollIntoView({ behavior: "smooth", block: "nearest" });

    try {
      const response = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, type, resolution, ext })
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        showError(data.error || "Failed to start download task.");
        progressContainer.style.display = "none";
        return;
      }

      const taskId = data.task_id;
      pollProgress(taskId);

    } catch (err) {
      showError("Failed to communicate with server. Please try again.");
      progressContainer.style.display = "none";
    }
  }

  function pollProgress(taskId) {
    if (activePollInterval) clearInterval(activePollInterval);
    let errorCount = 0;

    activePollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/api/progress/${taskId}`);
        if (!res.ok) {
          errorCount++;
          if (errorCount > 6) {
            clearInterval(activePollInterval);
            showError("Download session lost. Please try again.");
          }
          return;
        }
        errorCount = 0;

        const data = await res.json();

        if (data.status === "downloading") {
          const pct = Math.min(Math.max(data.percent || 0, 0), 95);
          progressBarFill.style.width = `${pct}%`;
          progressPercent.textContent = `${pct}%`;
          progressStatusText.textContent = "Downloading media stream...";
          progressSpeed.textContent = `Speed: ${data.speed || '--'}`;
          progressEta.textContent = `ETA: ${data.eta || '--'}`;
        } else if (data.status === "converting") {
          progressBarFill.style.width = "98%";
          progressPercent.textContent = "98%";
          progressStatusText.textContent = "Finalizing & merging audio/video with FFmpeg...";
          progressSpeed.textContent = "Processing...";
          progressEta.textContent = "Almost ready...";
        } else if (data.status === "completed") {
          clearInterval(activePollInterval);
          progressBarFill.style.width = "100%";
          progressPercent.textContent = "100%";
          progressStatusText.textContent = "✓ Ready! Download starting...";
          progressSpeed.textContent = `File: ${data.filename}`;
          progressEta.textContent = `Size: ${data.filesize_str || 'Ready'}`;

          const downloadUrl = `/api/file/${taskId}`;
          directDownloadAnchor.href = downloadUrl;
          directDownloadAnchor.setAttribute("download", data.filename);
          progressDownloadReady.style.display = "block";

          // Trigger browser download via invisible iframe or link click
          const triggerLink = document.createElement("a");
          triggerLink.href = downloadUrl;
          triggerLink.download = data.filename;
          document.body.appendChild(triggerLink);
          triggerLink.click();
          document.body.removeChild(triggerLink);

        } else if (data.status === "error") {
          clearInterval(activePollInterval);
          showError(data.error || "Download encountered an error.");
          progressStatusText.textContent = "Failed";
          progressBarFill.style.width = "0%";
        }
      } catch (err) {
        console.error("Progress poll error:", err);
      }
    }, 800);
  }
});
