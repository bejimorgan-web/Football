const { app, BrowserWindow, Menu, ipcMain, dialog, shell } = require("electron");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const { ProviderStore } = require("./src/database");

const DEFAULT_DESKTOP_BACKEND_URL = String(process.env.DESKTOP_API_URL || process.env.API_BASE_URL || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
const DEFAULT_PUBLIC_API_BASE_URL = DEFAULT_DESKTOP_BACKEND_URL;

let mainWindow = null;
let platformClientsWindow = null;
let providerStore = null;
let session = null;
let currentRoute = "login";
let mainWindowRecoveryInFlight = false;

const updateState = {
  status: "idle",
  currentVersion: app.getVersion(),
  latestVersion: "",
  updateAvailable: false,
  mandatory: false,
  releaseNotes: "",
  releaseDate: "",
  progressPercent: 0,
  error: "",
};

const masterLiveState = {
  status: "idle",
  version: null,
  streams: { items: [] },
  liveScores: { matches: [] },
  standings: { standings: [] },
  fixtures: { matches: [] },
  lastUpdatedAt: "",
  error: "",
};

function defaultSession() {
  return {
    apiToken: "",
    deviceId: machineFingerprint(),
    serverId: "",
    adminId: "",
    role: "",
    tenantId: "default",
    adminEmail: "",
    adminName: "",
    planId: "",
    subscriptionStatus: "",
    accountStatus: "",
    licenseKey: "",
    licenseToken: "",
    licenseStatus: "",
    licenseExpiresAt: "",
    licenseActivatedAt: "",
    licensePlan: "",
  };
}

function sessionFilePath() {
  return path.join(app.getPath("userData"), "session.json");
}

function desktopLogPath() {
  return path.join(app.getPath("userData"), "desktop-main.log");
}

function backupLogPath() {
  return path.join(app.getPath("userData"), "desktop-backups.json");
}

function writeDesktopLog(message, error = null) {
  try {
    const lines = [`[${new Date().toISOString()}] ${message}`];
    if (error) {
      lines.push(String(error.stack || error.message || error));
    }
    fs.mkdirSync(path.dirname(desktopLogPath()), { recursive: true });
    fs.appendFileSync(desktopLogPath(), `${lines.join("\n")}\n`, "utf8");
  } catch (_) {
    // Logging must never crash the desktop process.
  }
}

function machineFingerprint() {
  const raw = [
    os.hostname(),
    os.platform(),
    os.release(),
    os.arch(),
    process.env.COMPUTERNAME || "",
    process.env.PROCESSOR_IDENTIFIER || "",
  ].join("|");
  return crypto.createHash("sha256").update(raw).digest("hex");
}

function machineNetworkInfo() {
  return {
    serverDomain: os.hostname(),
    serverIp: "127.0.0.1",
    hardwareHash: machineFingerprint(),
  };
}

function authPagePath(pageName = "login") {
  return path.join(__dirname, "src", "ui", "auth", `${pageName}.html`);
}

function dashboardPath() {
  return path.join(__dirname, "src", "index.html");
}

function platformClientsDashboardPath() {
  return path.join(__dirname, "src", "ui", "admin", "platform_clients_dashboard.html");
}

function loadSession() {
  try {
    const raw = fs.readFileSync(sessionFilePath(), "utf8");
    session = { ...defaultSession(), ...JSON.parse(raw || "{}") };
  } catch (_) {
    session = defaultSession();
  }
  return session;
}

function saveSession(patch = {}) {
  session = { ...defaultSession(), ...(session || {}), ...(patch || {}) };
  fs.mkdirSync(path.dirname(sessionFilePath()), { recursive: true });
  fs.writeFileSync(sessionFilePath(), JSON.stringify(session, null, 2), "utf8");
  return session;
}

function clearSession() {
  session = defaultSession();
  saveSession(session);
  return session;
}

function normalizeBackendUrl(rawUrl) {
  const fallback = DEFAULT_DESKTOP_BACKEND_URL;
  return String(rawUrl || fallback).trim().replace(/\/+$/, "") || fallback;
}

function normalizeApiEndpointUrl(rawUrl, fallback = "") {
  return String(rawUrl || fallback).trim().replace(/\/+$/, "") || String(fallback || "").trim();
}

function isValidHttpUrl(value) {
  try {
    const parsed = new URL(String(value || "").trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (_) {
    return false;
  }
}

function getApiEndpointConfig(settings, kind) {
  const endpointKind = kind === "public" ? "public" : "backend";
  const fallbackUrl = endpointKind === "public" ? DEFAULT_PUBLIC_API_BASE_URL : DEFAULT_DESKTOP_BACKEND_URL;
  const config = endpointKind === "public" ? settings?.publicApi : settings?.backendApi;
  return {
    kind: endpointKind,
    url: normalizeApiEndpointUrl(config?.url, endpointKind === "public" ? settings?.apiBaseUrl : settings?.backendUrl || fallbackUrl),
    apiToken: String(config?.apiToken || "").trim(),
    connected: config?.connected === true,
  };
}

function buildApiSettingsPatch(settings, kind, patch = {}) {
  const backendApi = getApiEndpointConfig(settings, "backend");
  const publicApi = getApiEndpointConfig(settings, "public");
  const nextBackendApi = kind === "backend" ? { ...backendApi, ...patch } : backendApi;
  const nextPublicApi = kind === "public" ? { ...publicApi, ...patch } : publicApi;
  return {
    backendApi: {
      ...nextBackendApi,
      url: normalizeApiEndpointUrl(nextBackendApi.url, DEFAULT_DESKTOP_BACKEND_URL),
      apiToken: String(nextBackendApi.apiToken || "").trim(),
      connected: nextBackendApi.connected === true,
    },
    publicApi: {
      ...nextPublicApi,
      url: normalizeApiEndpointUrl(nextPublicApi.url, DEFAULT_PUBLIC_API_BASE_URL),
      apiToken: String(nextPublicApi.apiToken || "").trim(),
      connected: nextPublicApi.connected === true,
    },
    backendUrl: normalizeApiEndpointUrl(nextBackendApi.url, DEFAULT_DESKTOP_BACKEND_URL),
    apiBaseUrl: normalizeApiEndpointUrl(nextPublicApi.url, DEFAULT_PUBLIC_API_BASE_URL),
  };
}

async function testApiEndpointConnection(kind, draft = {}) {
  const settings = await getSettings();
  const current = getApiEndpointConfig(settings, kind);
  const next = {
    ...current,
    ...(draft || {}),
  };
  const url = normalizeApiEndpointUrl(
    next.url,
    kind === "public" ? DEFAULT_PUBLIC_API_BASE_URL : DEFAULT_DESKTOP_BACKEND_URL,
  );
  const apiToken = String(next.apiToken || "").trim();
  if (!url) {
    throw new Error("API URL is required.");
  }
  if (!isValidHttpUrl(url)) {
    throw new Error("API URL must start with http:// or https://.");
  }
  if (!apiToken) {
    throw new Error("API token is required.");
  }

  const probeUrl = `${url}/config/branding?tenant_id=master`;
  const response = await fetch(probeUrl, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${apiToken}`,
      "Content-Type": "application/json",
    },
  });
  const text = await response.text();
  const payload = text ? safeJsonParse(text) : {};
  if (!response.ok) {
    if (response.status === 401) {
      writeDesktopLog(
        `Backend 401 for ${pathname} auth_present=${Boolean(authToken)} device_present=${Boolean(headers["X-Device-Id"])} server_present=${Boolean(headers["X-Server-Id"])} tenant=${String(session?.tenantId || settings?.tenantId || "default")}`,
      );
    }
    const detail = payload?.detail || payload?.message || text || `Request failed with status ${response.status}.`;
    throw new Error(detail);
  }
  if (!payload || typeof payload !== "object" || (!payload.branding && !payload.tenant_id)) {
    throw new Error("API validation failed: branding JSON was not returned.");
  }
  return {
    ok: true,
    endpoint: {
      kind: current.kind,
      url,
      apiToken,
      connected: true,
    },
    payload,
  };
}

async function getSettings() {
  return providerStore.getSettings();
}

async function getBackendUrl() {
  const settings = await getSettings();
  return normalizeBackendUrl(getApiEndpointConfig(settings, "backend").url);
}

async function callBackend(pathname, options = {}) {
  const settings = await getSettings();
  const backendEndpoint = getApiEndpointConfig(settings, "backend");
  const url = `${normalizeBackendUrl(backendEndpoint.url)}${pathname}`;
  const headers = { ...(options.headers || {}) };
  const authToken = String(session?.apiToken || backendEndpoint.apiToken || "").trim();

  if (options.auth !== false && authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  if (!headers["X-Device-Id"] && session?.deviceId) {
    headers["X-Device-Id"] = session.deviceId;
  }
  if (!headers["X-Server-Id"] && session?.serverId) {
    headers["X-Server-Id"] = session.serverId;
  }

  let body = options.body;
  if (body != null && typeof body === "object" && !(body instanceof Buffer)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, {
      method: options.method || "GET",
      headers,
      body,
    });
  } catch (error) {
    const message = String(error?.cause?.code || error?.code || error?.message || error || "").trim();
    const detail = message || "backend unavailable";
    throw new Error(`Could not reach backend at ${url} (${detail}).`);
  }

  if (options.raw) {
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}.`);
    }
    return response;
  }

  const text = await response.text();
  const payload = text ? safeJsonParse(text) : {};
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || text || `Request failed with status ${response.status}.`;
    throw new Error(detail);
  }
  return payload;
}

function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch (_) {
    return { value };
  }
}

function isDefaultTenantId(value) {
  return String(value || "").trim().toLowerCase() === "default";
}

function resolveTenantId(settings, explicitTenantId = null) {
  const requestedTenantId = String(explicitTenantId || "").trim();
  if (requestedTenantId) {
    return requestedTenantId;
  }

  const sessionTenantId = String(session?.tenantId || "").trim();
  const settingsTenantId = String(settings?.tenantId || "").trim();
  const isMaster = String(session?.role || "").trim().toLowerCase() === "master";

  if (isMaster) {
    if (settingsTenantId && !isDefaultTenantId(settingsTenantId)) {
      return settingsTenantId;
    }
    if (sessionTenantId) {
      return sessionTenantId;
    }
    return "master";
  }

  if (sessionTenantId) {
    return sessionTenantId;
  }
  if (settingsTenantId) {
    return settingsTenantId;
  }
  return "default";
}

function withTenant(pathname, settings, tenantId = null) {
  const resolvedTenantId = resolveTenantId(settings, tenantId);
  const separator = pathname.includes("?") ? "&" : "?";
  return `${pathname}${separator}tenant_id=${encodeURIComponent(resolvedTenantId)}`;
}

async function syncSessionTenantSetting() {
  if (!providerStore) {
    return;
  }
  const currentSettings = await providerStore.getSettings();
  const sessionTenantId = String(session?.tenantId || "").trim();
  const isMaster = String(session?.role || "").trim().toLowerCase() === "master";
  const currentTenantId = String(currentSettings?.tenantId || "").trim();
  const desiredTenantId = isMaster
    ? (
      (!currentTenantId || isDefaultTenantId(currentTenantId))
        ? (sessionTenantId || "master")
        : currentTenantId
    )
    : (sessionTenantId || "default");
  if (String(currentSettings?.tenantId || "").trim() !== desiredTenantId) {
    await providerStore.saveSettings({ ...currentSettings, tenantId: desiredTenantId });
  }
}

function applyAdminSession(admin, apiToken = session?.apiToken || "") {
  const adminPayload = admin || {};
  return saveSession({
    apiToken,
    adminId: String(adminPayload.admin_id || ""),
    role: String(adminPayload.role || ""),
    tenantId: String(adminPayload.tenant_id || "default"),
    adminEmail: String(adminPayload.email || ""),
    adminName: String(adminPayload.name || ""),
    planId: String(adminPayload.plan_id || ""),
    subscriptionStatus: String(adminPayload.subscription_status || ""),
    accountStatus: String(adminPayload.status || ""),
    serverId: String(adminPayload.server_id || ""),
    deviceId: String(adminPayload.device_id || session?.deviceId || machineFingerprint()),
  });
}

async function validateCurrentSession() {
  if (!session?.apiToken) {
    return { authenticated: false, route: "login" };
  }

  try {
    const payload = await callBackend("/admin/validate");
    applyAdminSession(payload.admin || {}, session.apiToken);
    await syncSessionTenantSetting();
  } catch (error) {
    const message = String(error.message || "");
    if (message.toLowerCase().includes("expired")) {
      return { authenticated: false, route: "renewal" };
    }
    clearSession();
    return { authenticated: false, route: "login" };
  }

  if (String(session.subscriptionStatus || "").toLowerCase() === "expired") {
    return { authenticated: false, route: "renewal" };
  }

  if (String(session.role || "").toLowerCase() === "master") {
    return { authenticated: true, route: "dashboard" };
  }

  if (!String(session.licenseToken || "").trim()) {
    return { authenticated: true, route: "license" };
  }

  try {
    await callBackend("/license/validate", {
      method: "POST",
      auth: false,
      body: {
        license_key: session.licenseKey,
        license_token: session.licenseToken,
        device_id: session.deviceId,
      },
    });
  } catch (_) {
    return { authenticated: true, route: "license" };
  }

  return { authenticated: true, route: "dashboard" };
}

function setLoginMenu() {
  const template = [
    {
      label: "File",
      submenu: [{ role: "quit", label: "Exit" }],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Documentation",
          click: () => shell.openPath(path.join(__dirname, "README.md")),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function sendMenuAction(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("menu:action", payload);
  }
}

function setDashboardMenu() {
  const isMaster = String(session?.role || "").toLowerCase() === "master";
  const template = [
    {
      label: "File",
      submenu: [
        { label: "Logout", click: () => sendMenuAction({ action: "logout" }) },
        { type: "separator" },
        { role: "quit", label: "Exit" },
      ],
    },
    {
      label: "Tools",
      submenu: [
        { label: "Backup", click: () => sendMenuAction({ section: "backups", action: "backup-now" }) },
        { label: "Security Center", click: () => sendMenuAction({ section: "security", action: "security-center" }) },
        { label: "System Information", click: () => sendMenuAction({ section: "branding", panel: "server", action: "system-information" }) },
      ],
    },
    {
      label: "Help",
      submenu: [
        { label: "Check for Updates", click: () => sendMenuAction({ section: "branding", panel: "server", action: "check-for-updates" }) },
      ],
    },
  ];

  if (isMaster) {
    template.splice(2, 0, {
      label: "View",
      submenu: [
        { label: "Users", click: () => sendMenuAction({ section: "users", action: "users" }) },
        { label: "Platform Clients Dashboard", click: () => openPlatformClientsDashboardWindow() },
      ],
    });
  }

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1180,
    minHeight: 760,
    title: "Gito IPTV Control Panel",
    icon: path.join(__dirname, "build", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.on("render-process-gone", (_, details) => {
    writeDesktopLog(`Main window renderer exited: ${details.reason || "unknown"} (exitCode=${details.exitCode ?? "n/a"})`);
    void recoverMainWindow("renderer exited");
  });

  mainWindow.webContents.on("did-fail-load", (_, errorCode, errorDescription, validatedURL, isMainFrame) => {
    if (!isMainFrame) {
      return;
    }
    writeDesktopLog(`Main window failed to load route ${currentRoute}: ${errorDescription} (${errorCode}) ${validatedURL || ""}`.trim());
    void recoverMainWindow("load failure");
  });
}

async function loadMainRoute(route) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
  }

  currentRoute = route;
  writeDesktopLog(`Navigating to route: ${route}`);

  if (route === "dashboard") {
    setDashboardMenu();
    await mainWindow.loadFile(dashboardPath());
    return;
  }

  setLoginMenu();
  await mainWindow.loadFile(authPagePath(route));
}

async function navigateForSession() {
  const state = await validateCurrentSession();
  await loadMainRoute(state.route);
}

async function recoverMainWindow(reason) {
  if (mainWindowRecoveryInFlight) {
    return;
  }
  mainWindowRecoveryInFlight = true;
  writeDesktopLog(`Attempting main window recovery after ${reason}.`);
  try {
    if (!mainWindow || mainWindow.isDestroyed()) {
      createWindow();
    }
    await navigateForSession();
  } catch (error) {
    writeDesktopLog("Main window recovery failed. Falling back to login route.", error);
    try {
      await loadMainRoute("login");
    } catch (loginError) {
      writeDesktopLog("Unable to load login route during recovery.", loginError);
    }
  } finally {
    mainWindowRecoveryInFlight = false;
  }
}

function openPlatformClientsDashboardWindow() {
  if (String(session?.role || "").toLowerCase() !== "master") {
    throw new Error("Only master admins can open the platform clients dashboard.");
  }
  if (platformClientsWindow && !platformClientsWindow.isDestroyed()) {
    platformClientsWindow.focus();
    return platformClientsWindow;
  }

  platformClientsWindow = new BrowserWindow({
    width: 1420,
    height: 900,
    minWidth: 1160,
    minHeight: 760,
    title: "Platform Clients Dashboard",
    icon: path.join(__dirname, "build", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  platformClientsWindow.on("closed", () => {
    platformClientsWindow = null;
  });

  platformClientsWindow.loadFile(platformClientsDashboardPath());
  return platformClientsWindow;
}

function requireMasterSession(action = "perform this action") {
  if (String(session?.role || "").toLowerCase() !== "master") {
    throw new Error(`Only master admins can ${action}.`);
  }
}

async function syncActiveProviderToBackend() {
  const settings = await providerStore.getSettings();
  const activeProvider = session?.adminId ? await providerStore.getActiveProvider(session.adminId) : null;
  const backendApi = getApiEndpointConfig(settings, "backend");
  const publicApi = getApiEndpointConfig(settings, "public");
  const payload = {
    backend_url: backendApi.url,
    api_base_url: publicApi.url || DEFAULT_PUBLIC_API_BASE_URL,
    xtream_server_url: activeProvider?.type === "xtream" ? activeProvider.xtreamServerUrl : "",
    xtream_username: activeProvider?.type === "xtream" ? activeProvider.xtreamUsername : "",
    xtream_password: activeProvider?.type === "xtream" ? activeProvider.xtreamPassword : "",
    m3u_playlist_url: activeProvider?.type === "m3u" ? activeProvider.m3uPlaylistUrl : "",
    cache_ttl_seconds: Number(activeProvider?.cacheTtlSeconds || 300),
  };

  if (session?.apiToken) {
    await callBackend(withTenant("/admin/config", settings), {
      method: "POST",
      body: payload,
    }).catch(() => null);
  }

  return { payload };
}

function buildBootstrapPayload(providers = [], activeProvider = null, settings = null) {
  return {
    providers,
    activeProvider,
    settings,
    session,
    updateState,
    masterLiveState,
  };
}

function loadBackupLogState() {
  try {
    const raw = fs.readFileSync(backupLogPath(), "utf8");
    const parsed = JSON.parse(raw || "{}");
    return {
      recent_logs: Array.isArray(parsed?.recent_logs) ? parsed.recent_logs : [],
      task_logs: Array.isArray(parsed?.task_logs) ? parsed.task_logs : [],
    };
  } catch (_) {
    return {
      recent_logs: [],
      task_logs: [],
    };
  }
}

function saveBackupLogState(state = {}) {
  const payload = {
    recent_logs: Array.isArray(state.recent_logs) ? state.recent_logs.slice(0, 20) : [],
    task_logs: Array.isArray(state.task_logs) ? state.task_logs.slice(0, 50) : [],
  };
  fs.mkdirSync(path.dirname(backupLogPath()), { recursive: true });
  fs.writeFileSync(backupLogPath(), JSON.stringify(payload, null, 2), "utf8");
  return payload;
}

function recordBackupTask(entry = {}) {
  const current = loadBackupLogState();
  const recentEntry = {
    success: entry.success === true,
    started_at: entry.started_at || new Date().toISOString(),
    finished_at: entry.finished_at || new Date().toISOString(),
    archive_path: String(entry.archive_path || ""),
    error: String(entry.error || ""),
  };
  const taskEntry = {
    type: String(entry.type || "backup"),
    success: recentEntry.success,
    started_at: recentEntry.started_at,
    finished_at: recentEntry.finished_at,
    archive_path: recentEntry.archive_path,
    error: recentEntry.error,
  };
  return saveBackupLogState({
    recent_logs: [recentEntry, ...(current.recent_logs || [])],
    task_logs: [taskEntry, ...(current.task_logs || [])],
  });
}

async function listBackupArchives(settings = null) {
  const currentSettings = settings || await getSettings();
  const backupDir = String(currentSettings?.backupPath || "").trim();
  if (!backupDir) {
    return [];
  }
  try {
    fs.mkdirSync(backupDir, { recursive: true });
    return fs.readdirSync(backupDir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".json"))
      .map((entry) => {
        const archivePath = path.join(backupDir, entry.name);
        const stats = fs.statSync(archivePath);
        return {
          name: entry.name,
          path: archivePath,
          modified_at: stats.mtime.toISOString(),
          size: stats.size,
        };
      })
      .sort((left, right) => String(right.modified_at).localeCompare(String(left.modified_at)));
  } catch (_) {
    return [];
  }
}

async function defaultBackupStatus() {
  const settings = await getSettings();
  const logs = loadBackupLogState();
  return {
    configured: settings,
    python: { available: true, executable: "Desktop JSON snapshot" },
    backups: await listBackupArchives(settings),
    recent_logs: logs.recent_logs,
    task_logs: logs.task_logs,
  };
}

async function runDesktopBackupNow() {
  const settings = await getSettings();
  const backupDir = String(settings?.backupPath || "").trim();
  if (!backupDir) {
    throw new Error("Backup folder is required.");
  }
  const sourcePath = providerStore.getStoragePath();
  const startedAt = new Date().toISOString();
  const stamp = startedAt.replace(/[:.]/g, "-");
  const archivePath = path.join(backupDir, `desktop-settings-${stamp}.json`);
  try {
    fs.mkdirSync(backupDir, { recursive: true });
    fs.copyFileSync(sourcePath, archivePath);
    const logs = recordBackupTask({
      type: "backup",
      success: true,
      started_at: startedAt,
      finished_at: new Date().toISOString(),
      archive_path: archivePath,
    });
    writeDesktopLog(`Backup completed: ${archivePath}`);
    return {
      result: { status: "completed", archive_path: archivePath },
      status: {
        configured: settings,
        python: { available: true, executable: "Desktop JSON snapshot" },
        backups: await listBackupArchives(settings),
        recent_logs: logs.recent_logs,
        task_logs: logs.task_logs,
      },
    };
  } catch (error) {
    const logs = recordBackupTask({
      type: "backup",
      success: false,
      started_at: startedAt,
      finished_at: new Date().toISOString(),
      archive_path: archivePath,
      error: error.message,
    });
    writeDesktopLog("Backup failed.", error);
    return {
      result: { status: "failed", error: error.message },
      status: {
        configured: settings,
        python: { available: true, executable: "Desktop JSON snapshot" },
        backups: await listBackupArchives(settings),
        recent_logs: logs.recent_logs,
        task_logs: logs.task_logs,
      },
    };
  }
}

async function restoreDesktopBackup(archivePath) {
  const settings = await getSettings();
  const sourcePath = String(archivePath || "").trim();
  if (!sourcePath) {
    throw new Error("Backup archive path is required.");
  }
  if (!fs.existsSync(sourcePath)) {
    throw new Error("Backup archive was not found.");
  }
  const targetPath = providerStore.getStoragePath();
  const startedAt = new Date().toISOString();
  try {
    fs.copyFileSync(sourcePath, targetPath);
    await providerStore.reload();
    const logs = recordBackupTask({
      type: "restore",
      success: true,
      started_at: startedAt,
      finished_at: new Date().toISOString(),
      archive_path: sourcePath,
    });
    writeDesktopLog(`Backup restored: ${sourcePath}`);
    return {
      result: { status: "completed", archive_path: sourcePath },
      status: {
        configured: await getSettings(),
        python: { available: true, executable: "Desktop JSON snapshot" },
        backups: await listBackupArchives(await getSettings()),
        recent_logs: logs.recent_logs,
        task_logs: logs.task_logs,
      },
    };
  } catch (error) {
    const logs = recordBackupTask({
      type: "restore",
      success: false,
      started_at: startedAt,
      finished_at: new Date().toISOString(),
      archive_path: sourcePath,
      error: error.message,
    });
    writeDesktopLog("Backup restore failed.", error);
    return {
      result: { status: "failed", error: error.message },
      status: {
        configured: settings,
        python: { available: true, executable: "Desktop JSON snapshot" },
        backups: await listBackupArchives(settings),
        recent_logs: logs.recent_logs,
        task_logs: logs.task_logs,
      },
    };
  }
}

function defaultRuntimeStatus(settings) {
  const backendApi = getApiEndpointConfig(settings || {}, "backend");
  return {
    mode: "external",
    managed: false,
    running: false,
    reachable: false,
    pid: null,
    url: normalizeBackendUrl(backendApi.url),
    python: { available: false, executable: "" },
    startedAt: "",
    logPath: "",
    lastError: "",
  };
}

function setupIpcHandlers() {
  ipcMain.handle("auth:get-status", async () => {
    const settings = await getSettings();
    return {
      authenticated: Boolean(session?.apiToken),
      deviceId: session.deviceId,
      backendUrl: normalizeBackendUrl(getApiEndpointConfig(settings, "backend").url),
      session,
    };
  });

  ipcMain.handle("auth:register", async (_, payload) => {
    const response = await callBackend("/admin/register", {
      method: "POST",
      auth: false,
      body: {
        name: payload.name,
        email: payload.email,
        password: payload.password,
        plan_id: payload.planId || "trial",
        payment_provider: payload.paymentProvider || "",
        payment_reference: payload.paymentReference || "",
        device_id: payload.deviceId || session.deviceId,
      },
    });
    applyAdminSession(response.admin || {}, response.api_token || "");
    await syncSessionTenantSetting();
    return { authenticated: true, session };
  });

  ipcMain.handle("auth:login", async (_, payload) => {
    const response = await callBackend("/admin/login", {
      method: "POST",
      auth: false,
      body: {
        email: payload.email,
        password: payload.password,
        device_id: payload.deviceId || session.deviceId,
      },
    });
    applyAdminSession(response.admin || {}, response.api_token || "");
    await syncSessionTenantSetting();
    return { authenticated: true, session };
  });

  ipcMain.handle("auth:renew", async (_, payload) => {
    const response = await callBackend("/admin/renew", {
      method: "POST",
      auth: false,
      body: {
        api_token: session.apiToken,
        plan_id: payload.planId || "1_year",
        payment_provider: payload.paymentProvider || "",
        payment_reference: payload.paymentReference || "",
      },
    });
    applyAdminSession(response.admin || {}, session.apiToken);
    await syncSessionTenantSetting();
    return { authenticated: true, session };
  });

  ipcMain.handle("auth:logout", async () => {
    clearSession();
    if (platformClientsWindow && !platformClientsWindow.isDestroyed()) {
      platformClientsWindow.close();
    }
    await loadMainRoute("login");
    return { authenticated: false, session };
  });

  ipcMain.on("auth:logged-in", () => {
    navigateForSession().catch(() => loadMainRoute("login"));
  });

  ipcMain.handle("license:get-status", async () => {
    let remoteLicense = null;
    let validation = { valid: false, reason: "License activation required." };

    if (session.apiToken) {
      remoteLicense = await callBackend("/license/generate", {
        method: "POST",
        body: { admin_id: session.adminId, activation_limit: 1 },
      }).then((payload) => payload.license || null).catch(() => null);
    }

    if (session.licenseToken) {
      validation = await callBackend("/license/validate", {
        method: "POST",
        auth: false,
        body: {
          license_token: session.licenseToken,
          device_id: session.deviceId,
        },
      }).then((payload) => ({
        valid: true,
        reason: "",
        ...(payload || {}),
      })).catch((error) => ({
        valid: false,
        reason: error.message,
      }));
    }

    return { session, remoteLicense, validation };
  });

  ipcMain.handle("license:generate", async () => {
    const payload = await callBackend("/license/generate", {
      method: "POST",
      body: { admin_id: session.adminId, activation_limit: 1 },
    });
    return { license: payload.license, session };
  });

  ipcMain.handle("license:activate", async (_, payload) => {
    const result = await callBackend("/license/activate", {
      method: "POST",
      auth: false,
      body: {
        license_key: payload.licenseKey,
        device_id: payload.deviceId || session.deviceId,
        app_version: payload.appVersion || app.getVersion(),
      },
    });

    saveSession({
      licenseKey: String(result.license?.license_key || payload.licenseKey || ""),
      licenseToken: String(result.license_token || ""),
      licenseStatus: String(result.license?.status || "active"),
      licenseExpiresAt: String(result.license?.expires_at || ""),
      licenseActivatedAt: String(result.license?.activated_at || ""),
      licensePlan: String(result.license?.subscription_plan || session.planId || ""),
    });

    await loadMainRoute("dashboard");
    return { result, session };
  });

  ipcMain.handle("app:get-default-api-url", async () => DEFAULT_PUBLIC_API_BASE_URL);

  ipcMain.handle("app:get-bootstrap", async () => {
    await syncSessionTenantSetting();
    const settings = await providerStore.getSettings();
    const providers = session?.adminId ? await providerStore.listProviders(session.adminId) : [];
    const activeProvider = session?.adminId ? await providerStore.getActiveProvider(session.adminId) : null;
    return buildBootstrapPayload(providers, activeProvider, settings);
  });

  ipcMain.handle("app:open-white-label-dashboard", async () => {
    openPlatformClientsDashboardWindow();
    return { ok: true };
  });

  ipcMain.handle("app:open-platform-clients-dashboard", async () => {
    openPlatformClientsDashboardWindow();
    return { ok: true };
  });

  ipcMain.handle("app:check-updates", async () => updateState);
  ipcMain.handle("app:get-update-state", async () => updateState);
  ipcMain.handle("app:get-master-live-state", async () => masterLiveState);
  ipcMain.handle("app:download-update", async () => ({ ok: false }));
  ipcMain.handle("app:install-update", async () => ({ ok: false }));

  ipcMain.handle("providers:save", async (_, payload) => {
    const provider = await providerStore.saveProvider(payload, session.adminId);
    await syncActiveProviderToBackend();
    return {
      provider,
      providers: await providerStore.listProviders(session.adminId),
      activeProvider: await providerStore.getActiveProvider(session.adminId),
    };
  });

  ipcMain.handle("providers:delete", async (_, providerId) => {
    await providerStore.deleteProvider(providerId, session.adminId);
    await syncActiveProviderToBackend();
    return {
      providers: await providerStore.listProviders(session.adminId),
      activeProvider: await providerStore.getActiveProvider(session.adminId),
    };
  });

  ipcMain.handle("providers:activate", async (_, providerId) => {
    await providerStore.setActiveProvider(providerId, session.adminId);
    await syncActiveProviderToBackend();
    return {
      providers: await providerStore.listProviders(session.adminId),
      activeProvider: await providerStore.getActiveProvider(session.adminId),
    };
  });

  ipcMain.handle("settings:save", async (_, payload) => {
    await providerStore.saveSettings(payload || {});
    await syncActiveProviderToBackend();
    return providerStore.getSettings();
  });

  ipcMain.handle("settings:api-test", async (_, payload) => {
    requireMasterSession("manage platform API endpoints");
    const kind = payload?.kind === "public" ? "public" : "backend";
    return testApiEndpointConnection(kind, {
      url: payload?.url || "",
      apiToken: payload?.apiToken || "",
    });
  });

  ipcMain.handle("settings:api-connect", async (_, payload) => {
    requireMasterSession("manage platform API endpoints");
    const kind = payload?.kind === "public" ? "public" : "backend";
    const settings = await getSettings();
    const draftPatch = buildApiSettingsPatch(settings, kind, {
      url: payload?.url || "",
      apiToken: payload?.apiToken || "",
      connected: false,
    });
    await providerStore.saveSettings(draftPatch);
    await callBackend("/api/config", {
      method: "POST",
      body: {
        backendApi: draftPatch.backendApi,
        publicApi: draftPatch.publicApi,
        apiBaseUrl: draftPatch.publicApi.url,
      },
    }).catch(() => null);
    let tested;
    try {
      tested = await testApiEndpointConnection(kind, {
        url: payload?.url || "",
        apiToken: payload?.apiToken || "",
      });
    } catch (error) {
      return {
        settings: await providerStore.getSettings(),
        error: error.message,
      };
    }
    const patch = buildApiSettingsPatch(await getSettings(), kind, tested.endpoint);
    await providerStore.saveSettings(patch);
    writeDesktopLog(`${kind} API connected: url=${kind === "public" ? patch.publicApi.url : patch.backendApi.url} tenant=master`);
    await callBackend("/api/config", {
      method: "POST",
      body: {
        backendApi: patch.backendApi,
        publicApi: patch.publicApi,
        apiBaseUrl: patch.publicApi.url,
      },
    }).catch(() => null);
    await syncActiveProviderToBackend();
    return {
      settings: await providerStore.getSettings(),
      test: tested,
    };
  });

  ipcMain.handle("settings:api-disconnect", async (_, payload) => {
    requireMasterSession("manage platform API endpoints");
    const kind = payload?.kind === "public" ? "public" : "backend";
    const settings = await getSettings();
    const current = getApiEndpointConfig(settings, kind);
    const patch = buildApiSettingsPatch(settings, kind, {
      ...current,
      connected: false,
    });
    await providerStore.saveSettings(patch);
    writeDesktopLog(`${kind} API disconnected: url=${kind === "public" ? patch.publicApi.url : patch.backendApi.url} tenant=master`);
    await callBackend("/api/config", {
      method: "POST",
      body: {
        backendApi: patch.backendApi,
        publicApi: patch.publicApi,
        apiBaseUrl: patch.publicApi.url,
      },
    }).catch(() => null);
    await syncActiveProviderToBackend();
    return {
      settings: await providerStore.getSettings(),
    };
  });

  ipcMain.handle("backend:runtime-status", async () => {
    const settings = await providerStore.getSettings();
    const remote = await callBackend(withTenant("/admin/status", settings), { auth: true }).catch(() => null);
    return {
      ...defaultRuntimeStatus(settings),
      reachable: Boolean(remote),
      running: Boolean(remote),
      remote,
    };
  });

  ipcMain.handle("backup:status", async () => defaultBackupStatus());
  ipcMain.handle("backup:run", async () => runDesktopBackupNow());
  ipcMain.handle("backup:restore", async (_, archivePath) => restoreDesktopBackup(archivePath));

  ipcMain.handle("backend:sync-active-provider", async () => syncActiveProviderToBackend());

  ipcMain.handle("backend:active-providers", async () => {
    const settings = await providerStore.getSettings();
    return callBackend(withTenant("/admin/streams", settings), { auth: true });
  });

  const tenantPost = (name, route) => {
    ipcMain.handle(name, async (_, payload) => {
      return callBackend(route, {
        method: "POST",
        body: payload || {},
      });
    });
  };

  const backendPost = (name, routeBuilder) => {
    ipcMain.handle(name, async (_, payload) => {
      const settings = await providerStore.getSettings();
      const route = typeof routeBuilder === "function" ? routeBuilder(payload, settings) : routeBuilder;
      return callBackend(withTenant(route, settings), {
        method: "POST",
        body: payload || {},
      });
    });
  };

  const backendGet = (name, routeBuilder) => {
    ipcMain.handle(name, async (_, payload) => {
      const settings = await providerStore.getSettings();
      const route = typeof routeBuilder === "function" ? routeBuilder(payload, settings) : routeBuilder;
      return callBackend(withTenant(route, settings));
    });
  };

  const backendDelete = (name, routeBuilder) => {
    ipcMain.handle(name, async (_, payload) => {
      const settings = await providerStore.getSettings();
      const route = typeof routeBuilder === "function" ? routeBuilder(payload, settings) : routeBuilder;
      return callBackend(withTenant(route, settings), {
        method: "DELETE",
      });
    });
  };

  tenantPost("backend:tenant-login", "/tenant/login");
  backendGet("backend:tenant-profile", (_, settings) => `/tenant/profile?tenant_id=${encodeURIComponent(settings.tenantId || "default")}`);
  backendGet("backend:tenant-list", "/admin/tenants");
  backendPost("backend:tenant-save", "/admin/tenants");
  backendGet("backend:branding-get", "/admin/branding");
  backendPost("backend:branding-save", "/admin/branding");
  backendGet("backend:setup-status", "/admin/setup-status");
  backendPost("backend:setup-complete", "/admin/setup-complete");
  ipcMain.handle("backend:validate-device", async () => {
    const settings = await providerStore.getSettings();
    return callBackend(withTenant("/admin/validate-device", settings), {
      method: "POST",
      body: {
        api_token: session.apiToken,
        device_id: session.deviceId,
        server_id: session.serverId,
      },
    });
  });
  ipcMain.handle("backend:fetch-streams", async (_, providerId) => {
    const settings = await providerStore.getSettings();
    const providerQuery = providerId ? `?provider_id=${encodeURIComponent(providerId)}` : "";
    const payload = await callBackend(withTenant(`/admin/streams${providerQuery}`, settings));
    const providerGroups = await callBackend(withTenant(`/provider/groups${providerQuery}`, settings)).catch(() => ({ items: [] }));
    return { ...payload, groups: providerGroups.items || payload.groups || [] };
  });
  backendGet("backend:fetch-approved", "/admin/streams/approved");
  backendGet("backend:fetch-users", "/admin/users");
  backendGet("backend:fetch-online-users", "/admin/users/online");
  backendGet("backend:analytics-live", "/analytics/live");
  backendGet("backend:analytics-streams", "/analytics/streams");
  backendGet("backend:analytics-top-matches", "/analytics/top-matches");
  backendGet("backend:analytics-top-competitions", "/analytics/top-competitions");
  backendGet("backend:analytics-daily-viewers", "/analytics/daily-viewers");
  backendGet("backend:analytics-countries", "/analytics/countries");
  backendGet("backend:white-label-installs", "/admin/platform_clients/dashboard");
  backendGet("backend:white-label-subscriptions", "/admin/platform_clients/analytics");
  backendPost("backend:mobile-build", "/mobile/generate-app");
  backendGet("backend:mobile-build-preflight", "/mobile/preflight");
  ipcMain.handle("backend:mobile-build-cancel", async (_, buildId) => callBackend(`/mobile/build/cancel/${encodeURIComponent(buildId || "")}`, { method: "POST" }));
  ipcMain.handle("backend:mobile-build-status", async (_, buildId) => callBackend(`/mobile/build/status/${encodeURIComponent(buildId || "")}`));
  ipcMain.handle("backend:mobile-build-history", async () => callBackend("/mobile/build/history"));
  ipcMain.handle("backend:mobile-build-download", async (_, payload) => {
    const response = await callBackend(`/mobile/download/${encodeURIComponent(payload?.buildId || "")}`, {
      raw: true,
    });
    const target = path.join(app.getPath("downloads"), String(payload?.fileName || "mobile-build.apk"));
    fs.writeFileSync(target, Buffer.from(await response.arrayBuffer()));
    return { path: target };
  });
  backendGet("backend:apk-versions", "/admin/apk-versions");
  ipcMain.handle("backend:upload-apk", async (_, payload) => callBackend("/admin/upload-apk", { method: "POST", body: payload || {} }));
  ipcMain.handle("backend:set-latest-apk", async (_, payload) => callBackend(`/admin/apk-versions/${encodeURIComponent(payload?.id || "")}/set-latest`, { method: "POST", body: { force_update: Boolean(payload?.force_update) } }));
  ipcMain.handle("backend:updates-latest", async () => {
    try {
      return await callBackend(`/updates/latest?current_version=${encodeURIComponent(app.getVersion())}&platform=win32`, { auth: false });
    } catch (error) {
      writeDesktopLog("Latest update metadata fetch failed.", error);
      return {};
    }
  });
  ipcMain.handle("backend:updates-history", async () => {
    try {
      return await callBackend("/updates/history");
    } catch (error) {
      writeDesktopLog("Update history fetch failed.", error);
      return [];
    }
  });
  ipcMain.handle("backend:updates-publish", async (_, payload) => callBackend("/updates/publish", { method: "POST", body: payload || {} }));
  backendGet("backend:platform-clients", "/admin/platform_clients");
  ipcMain.handle("backend:platform-client-block", async (_, adminId) => callBackend(`/admin/platform_clients/${encodeURIComponent(adminId || "")}/block`, { method: "POST" }));
  ipcMain.handle("backend:platform-client-unblock", async (_, adminId) => callBackend(`/admin/platform_clients/${encodeURIComponent(adminId || "")}/unblock`, { method: "POST" }));
  ipcMain.handle("backend:platform-client-extend-trial", async (_, payload) => callBackend(`/admin/platform_clients/${encodeURIComponent(payload?.adminId || "")}/extend_trial`, { method: "POST", body: { days: Number(payload?.days || 0) } }));
  ipcMain.handle("backend:platform-client-reset-server", async (_, adminId) => callBackend(`/admin/platform_clients/${encodeURIComponent(adminId || "")}/reset_server`, { method: "POST" }));
  ipcMain.handle("backend:platform-client-delete", async (_, adminId) => callBackend(`/admin/platform_clients/${encodeURIComponent(adminId || "")}`, { method: "DELETE" }));
  ipcMain.handle("backend:branding-upload", async (_, payload) => callBackend(withTenant(`/admin/branding/upload_${payload?.kind || "logo"}`, await providerStore.getSettings()), { method: "POST", body: { data_url: payload?.dataUrl || "" } }));
  backendGet("backend:security-dashboard", "/admin/security");
  backendPost("backend:block-user", "/admin/block");
  backendPost("backend:unblock-user", "/admin/unblock");
  backendPost("backend:free-user", "/admin/users/free-access");
  backendPost("backend:remove-free-user", "/admin/users/remove-free-access");
  backendPost("backend:extend-user", "/admin/extend");
  backendPost("backend:extend-subscription", "/admin/extend");
  backendPost("backend:rename-user", "/admin/users/rename");
  backendPost("backend:restore-user-name", "/admin/users/restore-name");
  backendPost("backend:reset-device", "/admin/users/reset-device");
  backendPost("backend:set-vpn-policy", "/admin/users/set-vpn-policy");
  ipcMain.handle("backend:update-football-item", async (_, payload) => {
    const settings = await providerStore.getSettings();
    const itemId = encodeURIComponent(payload?.id || "");
    return callBackend(withTenant(`/football/${itemId}`, settings), {
      method: "PUT",
      body: {
        entity_type: payload?.entity_type || "",
        name: payload?.name || "",
        nation_id: payload?.nation_id || null,
        competition_id: payload?.competition_id || null,
        competition_type: payload?.competition_type || "league",
        logo_url: payload?.logo_url || "",
      },
    });
  });
  ipcMain.handle("backend:delete-football-item", async (_, payload) => {
    const settings = await providerStore.getSettings();
    const itemId = encodeURIComponent(payload?.id || "");
    const entityType = encodeURIComponent(payload?.entity_type || "");
    return callBackend(withTenant(`/football/${itemId}?entity_type=${entityType}`, settings), {
      method: "DELETE",
    });
  });
  backendGet("backend:fetch-nations", "/admin/nations");
  backendPost("backend:save-nation", "/admin/nations");
  backendDelete("backend:delete-nation", (nationId) => `/admin/nations/${encodeURIComponent(nationId || "")}`);
  ipcMain.handle("backend:fetch-competitions", async (_, nationId = null) => {
    const settings = await providerStore.getSettings();
    const suffix = nationId ? `?nation_id=${encodeURIComponent(nationId)}` : "";
    return callBackend(withTenant(`/admin/competitions${suffix}`, settings));
  });
  backendPost("backend:save-competition", "/admin/competitions");
  backendDelete("backend:delete-competition", (competitionId) => `/admin/competitions/${encodeURIComponent(competitionId || "")}`);
  ipcMain.handle("backend:fetch-clubs", async (_, payload = {}) => {
    const settings = await providerStore.getSettings();
    const params = new URLSearchParams();
    if (payload.nationId) params.set("nation_id", payload.nationId);
    if (payload.competitionId) params.set("competition_id", payload.competitionId);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return callBackend(withTenant(`/admin/clubs${suffix}`, settings));
  });
  backendPost("backend:save-club", "/admin/clubs");
  backendDelete("backend:delete-club", (clubId) => `/admin/clubs/${encodeURIComponent(clubId || "")}`);
  ipcMain.handle("backend:upload-asset", async (_, payload) => {
    return { url: payload?.data_url || payload?.dataUrl || "" };
  });
  backendPost("backend:approve-stream", "/admin/streams/approve");
  ipcMain.handle("backend:remove-approved", async (_, streamId) => {
    const settings = await providerStore.getSettings();
    return callBackend(withTenant(`/admin/streams/remove?stream_id=${encodeURIComponent(streamId || "")}`, settings), {
      method: "POST",
    });
  });
}

app.whenReady().then(async () => {
  process.on("uncaughtException", (error) => {
    writeDesktopLog("Uncaught exception in desktop main process.", error);
  });

  process.on("unhandledRejection", (reason) => {
    writeDesktopLog("Unhandled rejection in desktop main process.", reason instanceof Error ? reason : new Error(String(reason)));
  });

  providerStore = new ProviderStore(path.join(app.getPath("userData"), "desktop-data.db"));
  await providerStore.init();
  loadSession();
  setupIpcHandlers();
  createWindow();
  try {
    await navigateForSession();
  } catch (error) {
    writeDesktopLog("Initial navigation failed. Falling back to login route.", error);
    await loadMainRoute("login");
  }

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
      try {
        await navigateForSession();
      } catch (error) {
        writeDesktopLog("Activation navigation failed. Falling back to login route.", error);
        await loadMainRoute("login");
      }
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
