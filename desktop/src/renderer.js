const state = {
  settings: {
    backendUrl: "http://127.0.0.1:8000",
    backendApi: { url: "http://127.0.0.1:8000", apiToken: "", connected: false },
  },
  session: {},
  streams: [],
  filteredStreams: [],
  selectedStream: null,
  loading: false,
};

let hls = null;

const $ = (id) => document.getElementById(id);

const el = {
  workspaceTitle: $("workspaceTitle"),
  workspaceSubtitle: $("workspaceSubtitle"),
  welcomeLabel: $("welcomeLabel"),
  serverLabel: $("serverLabel"),
  statusLabel: $("statusLabel"),
  streamCountLabel: $("streamCountLabel"),
  backendUrlInput: $("backendUrlInput"),
  backendStatus: $("backendStatus"),
  testBackendButton: $("testBackendButton"),
  saveBackendButton: $("saveBackendButton"),
  refreshStreamsButton: $("refreshStreamsButton"),
  searchInput: $("searchInput"),
  streamList: $("streamList"),
  player: $("streamPlayer"),
  playerOverlay: $("playerOverlay"),
  selectedStreamName: $("selectedStreamName"),
  selectedStreamMeta: $("selectedStreamMeta"),
  selectedStreamUrl: $("selectedStreamUrl"),
  playButton: $("playButton"),
  stopButton: $("stopButton"),
};

function showToast(message, isError = false) {
  const toast = document.createElement("div");
  toast.className = `pill ${isError ? "danger" : "active"}`;
  toast.textContent = String(message || "");
  toast.style.position = "fixed";
  toast.style.right = "24px";
  toast.style.bottom = "24px";
  toast.style.zIndex = "9999";
  document.body.appendChild(toast);
  window.setTimeout(() => toast.remove(), 2800);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function streamUrlFor(item) {
  return String(item?.url || item?.stream_url || "").trim();
}

function filterStreams() {
  const query = String(el.searchInput?.value || "").trim().toLowerCase();
  if (!query) {
    state.filteredStreams = state.streams.slice();
    return;
  }
  state.filteredStreams = state.streams.filter((item) => {
    const haystack = [
      item?.name,
      item?.group,
      item?.id,
      item?.stream_id,
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderHeader() {
  el.welcomeLabel.textContent = state.session.adminName || "Local Operator";
  el.serverLabel.textContent = state.session.serverId || "-";
  el.statusLabel.textContent = state.loading ? "Loading streams..." : "Ready";
  el.streamCountLabel.textContent = String(state.streams.length);
  el.backendUrlInput.value = state.settings.backendApi?.url || state.settings.backendUrl || "";
  el.backendStatus.textContent = state.settings.backendApi?.connected ? "Connected" : "Saved";
}

function renderStreamList() {
  filterStreams();
  if (!state.filteredStreams.length) {
    el.streamList.innerHTML = `<div class="empty-state">${state.streams.length ? "No streams match your search." : "No streams returned from /streams."}</div>`;
    return;
  }
  el.streamList.innerHTML = state.filteredStreams.map((item) => {
    const selected = String(state.selectedStream?.id || state.selectedStream?.stream_id || "") === String(item?.id || item?.stream_id || "");
    return `
      <button class="channel-card${selected ? " active" : ""}" data-stream-id="${escapeHtml(item?.id || item?.stream_id || "")}">
        <div>
          <strong>${escapeHtml(item?.name || "Unnamed stream")}</strong>
          <div class="subtle">${escapeHtml(item?.group || "Ungrouped")}</div>
          <div class="subtle">ID: ${escapeHtml(item?.id || item?.stream_id || "-")}</div>
        </div>
      </button>
    `;
  }).join("");

  el.streamList.querySelectorAll("[data-stream-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const streamId = String(button.getAttribute("data-stream-id") || "");
      state.selectedStream = state.streams.find((item) => String(item?.id || item?.stream_id || "") === streamId) || null;
      renderPlayerPanel();
      renderStreamList();
      playSelectedStream().catch((error) => showToast(error.message, true));
    });
  });
}

function stopPlayback() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
  el.player.pause();
  el.player.removeAttribute("src");
  el.player.load();
  el.playerOverlay.textContent = "Select a stream to test playback.";
}

async function playSelectedStream() {
  const url = streamUrlFor(state.selectedStream);
  if (!url) {
    throw new Error("This stream does not include a playable URL.");
  }
  stopPlayback();
  if (window.Hls?.isSupported() && /\.m3u8($|\?)/i.test(url)) {
    hls = new window.Hls();
    hls.loadSource(url);
    hls.attachMedia(el.player);
  } else {
    el.player.src = url;
  }
  await el.player.play().catch(() => null);
  el.playerOverlay.textContent = "";
}

function renderPlayerPanel() {
  const stream = state.selectedStream;
  el.selectedStreamName.textContent = stream?.name || "No stream selected";
  el.selectedStreamMeta.textContent = stream
    ? `${stream.group || "Ungrouped"} | ID ${stream.id || stream.stream_id || "-"}`
    : "Choose a stream from the list to begin testing.";
  el.selectedStreamUrl.textContent = stream ? streamUrlFor(stream) || "No direct URL returned." : "-";
  el.playButton.disabled = !stream;
  el.stopButton.disabled = !stream;
  if (!stream) {
    stopPlayback();
  }
}

async function loadStreams() {
  state.loading = true;
  renderHeader();
  try {
    const payload = await window.desktopApi.fetchStreams();
    state.streams = Array.isArray(payload?.items) ? payload.items : [];
    if (state.selectedStream) {
      const selectedId = String(state.selectedStream?.id || state.selectedStream?.stream_id || "");
      state.selectedStream = state.streams.find((item) => String(item?.id || item?.stream_id || "") === selectedId) || null;
    }
    renderStreamList();
    renderPlayerPanel();
    showToast(`Loaded ${state.streams.length} streams.`);
  } catch (error) {
    state.streams = [];
    state.selectedStream = null;
    renderStreamList();
    renderPlayerPanel();
    showToast(error.message, true);
  } finally {
    state.loading = false;
    renderHeader();
  }
}

async function saveBackendSettings() {
  const url = String(el.backendUrlInput.value || "").trim();
  state.settings = await window.desktopApi.saveSettings({
    ...state.settings,
    backendUrl: url,
    backendApi: {
      ...(state.settings.backendApi || {}),
      url,
    },
  });
  renderHeader();
}

async function bootstrap() {
  const bootstrapData = await window.desktopApi.getBootstrap();
  state.settings = { ...state.settings, ...(bootstrapData?.settings || {}) };
  state.session = bootstrapData?.session || {};
  renderHeader();
  renderPlayerPanel();
  renderStreamList();
  await loadStreams();
}

el.searchInput.addEventListener("input", renderStreamList);
el.refreshStreamsButton.addEventListener("click", () => {
  loadStreams().catch((error) => showToast(error.message, true));
});
el.saveBackendButton.addEventListener("click", async () => {
  try {
    await saveBackendSettings();
    showToast("Backend URL saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});
el.testBackendButton.addEventListener("click", async () => {
  try {
    const result = await window.desktopApi.testApiEndpoint({
      kind: "backend",
      url: String(el.backendUrlInput.value || "").trim(),
      apiToken: "",
    });
    const resolvedUrl = result?.endpoint?.url || el.backendUrlInput.value.trim();
    await saveBackendSettings();
    el.backendUrlInput.value = resolvedUrl;
    showToast("Backend connection succeeded.");
  } catch (error) {
    showToast(error.message, true);
  }
});
el.playButton.addEventListener("click", () => {
  playSelectedStream().catch((error) => showToast(error.message, true));
});
el.stopButton.addEventListener("click", stopPlayback);

window.addEventListener("beforeunload", stopPlayback);

bootstrap().catch((error) => {
  showToast(error.message, true);
  renderHeader();
  renderPlayerPanel();
  renderStreamList();
});
