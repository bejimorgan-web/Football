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
let currentRoute = "dashboard";
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

function defaultServerId() {
  return `desktop-${machineFingerprint().slice(0, 12)}`;
}

function defaultSession() {
  return {
    apiToken: "",
    deviceId: machineFingerprint(),
    serverId: defaultServerId(),
    adminId: "local-desktop",
    role: "master",
    tenantId: "default",
    adminEmail: "local@desktop",
    adminName: "Local Operator",
    planId: "single-user",
    subscriptionStatus: "active",
    accountStatus: "active",
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
  session = normalizeSingleUserSession(session);
  return session;
}

function saveSession(patch = {}) {
  session = normalizeSingleUserSession({ ...defaultSession(), ...(session || {}), ...(patch || {}) });
  fs.mkdirSync(path.dirname(sessionFilePath()), { recursive: true });
  fs.writeFileSync(sessionFilePath(), JSON.stringify(session, null, 2), "utf8");
  return session;
}

function clearSession() {
  return saveSession(defaultSession());
}

function normalizeSingleUserSession(currentSession = {}) {
  const defaults = defaultSession();
  return {
    ...defaults,
    ...(currentSession || {}),
    apiToken: "",
    deviceId: String(currentSession?.deviceId || defaults.deviceId || "").trim() || defaults.deviceId,
    serverId: String(currentSession?.serverId || defaults.serverId || "").trim() || defaults.serverId,
    adminId: String(currentSession?.adminId || defaults.adminId || "").trim() || defaults.adminId,
    role: "master",
    tenantId: String(currentSession?.tenantId || defaults.tenantId || "default").trim() || "default",
    adminEmail: String(currentSession?.adminEmail || defaults.adminEmail || "").trim() || defaults.adminEmail,
    adminName: String(currentSession?.adminName || defaults.adminName || "").trim() || defaults.adminName,
    planId: String(currentSession?.planId || defaults.planId || "").trim() || defaults.planId,
    subscriptionStatus: String(currentSession?.subscriptionStatus || defaults.subscriptionStatus || "active").trim() || "active",
    accountStatus: String(currentSession?.accountStatus || defaults.accountStatus || "active").trim() || "active",
  };
}

async function ensureSingleUserSession({ persist = false } = {}) {
  session = normalizeSingleUserSession(session || {});
  if (persist) {
    saveSession(session);
  }
  await syncSessionTenantSetting();
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

  const probeUrl = `${url}/config/branding?tenant_id=master`;
  const response = await fetch(probeUrl, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });
  const text = await response.text();
  const payload = text ? safeJsonParse(text) : {};
  if (!response.ok) {
    if (response.status === 401) {
      writeDesktopLog(`Backend 401 for API endpoint probe ${probeUrl}`);
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
  const authToken = String(session?.apiToken || "").trim();
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

  writeDesktopLog(
    `Backend request ${options.method || "GET"} ${url} auth_required=false token=${maskToken(authToken)} device_id=${String(headers["X-Device-Id"] || "")} server_id=${String(headers["X-Server-Id"] || "")} headers=${JSON.stringify({
      ...headers,
    })}`,
  );

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
    if (response.status === 401) {
      writeDesktopLog(
        `Backend 401 for ${options.method || "GET"} ${url} token=${maskToken(authToken)} device_present=${Boolean(headers["X-Device-Id"])} server_present=${Boolean(headers["X-Server-Id"])} session_tenant=${String(session?.tenantId || "")} settings_tenant=${String(settings?.tenantId || "")} resolved_tenant=${resolveTenantId(settings)}`,
      );
    }
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

function maskToken(value) {
  const token = String(value || "").trim();
  if (!token) {
    return "";
  }
  if (token.length <= 8) {
    return `${token.slice(0, 2)}***${token.slice(-2)}`;
  }
  return `${token.slice(0, 4)}***${token.slice(-4)}`;
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

  if (sessionTenantId) {
    return sessionTenantId;
  }
  if (settingsTenantId && !isDefaultTenantId(settingsTenantId)) {
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
  const desiredTenantId = sessionTenantId || "default";
  if (String(currentSettings?.tenantId || "").trim() !== desiredTenantId) {
    await providerStore.saveSettings({ ...currentSettings, tenantId: desiredTenantId });
  }
}

function applyAdminSession(admin, apiToken = session?.apiToken || "") {
  const adminPayload = admin || {};
  return saveSession({
    apiToken: "",
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
  await ensureSingleUserSession({ persist: true });
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
  const template = [
    {
      label: "File",
      submenu: [
        { role: "reload", label: "Reload" },
        { role: "quit", label: "Exit" },
      ],
    },
    {
      label: "Help",
      submenu: [
        { label: "Documentation", click: () => shell.openPath(path.join(__dirname, "README.md")) },
      ],
    },
  ];

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

  currentRoute = "dashboard";
  writeDesktopLog(`Navigating to route: dashboard${route && route !== "dashboard" ? ` (requested ${route})` : ""}`);
  setDashboardMenu();
  await mainWindow.loadFile(dashboardPath());
}

async function navigateForSession() {
  await validateCurrentSession();
  await loadMainRoute("dashboard");
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
    writeDesktopLog("Main window recovery failed. Falling back to dashboard route.", error);
    try {
      await loadMainRoute("dashboard");
    } catch (dashboardError) {
      writeDesktopLog("Unable to load dashboard route during recovery.", dashboardError);
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

  await callBackend(withTenant("/admin/config", settings), {
    method: "POST",
    body: payload,
  }).catch(() => null);

  return { payload };
}

function buildBootstrapPayload(settings = null) {
  return {
    settings,
    session,
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
    await ensureSingleUserSession({ persist: true });
    const settings = await getSettings();
    return {
      authenticated: true,
      deviceId: session.deviceId,
      backendUrl: normalizeBackendUrl(getApiEndpointConfig(settings, "backend").url),
      session,
    };
  });

  ipcMain.handle("auth:register", async () => {
    await ensureSingleUserSession({ persist: true });
    return { authenticated: true, skipped: true, session };
  });

  ipcMain.handle("auth:login", async () => {
    await ensureSingleUserSession({ persist: true });
    return { authenticated: true, skipped: true, session };
  });

  ipcMain.handle("auth:renew", async () => {
    await ensureSingleUserSession({ persist: true });
    return { authenticated: true, skipped: true, session };
  });

  ipcMain.handle("auth:logout", async () => {
    await ensureSingleUserSession({ persist: true });
    if (platformClientsWindow && !platformClientsWindow.isDestroyed()) {
      platformClientsWindow.close();
    }
    await loadMainRoute("dashboard");
    return { authenticated: true, skipped: true, session };
  });

  ipcMain.on("auth:logged-in", () => {
    navigateForSession().catch(() => loadMainRoute("dashboard"));
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
    await ensureSingleUserSession({ persist: true });
    const settings = await providerStore.getSettings();
    return buildBootstrapPayload(settings);
  });

  ipcMain.handle("settings:save", async (_, payload) => {
    await providerStore.saveSettings(payload || {});
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

  ipcMain.handle("backend:fetch-streams", async () => {
    const settings = await providerStore.getSettings();
    return callBackend(withTenant("/streams?page=1&page_size=500&include_url=true", settings));
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
    writeDesktopLog("Initial navigation failed. Falling back to dashboard route.", error);
    await loadMainRoute("dashboard");
  }

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
      try {
        await navigateForSession();
      } catch (error) {
        writeDesktopLog("Activation navigation failed. Falling back to dashboard route.", error);
        await loadMainRoute("dashboard");
      }
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
