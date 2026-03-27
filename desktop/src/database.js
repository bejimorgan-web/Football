const fs = require("fs/promises");
const syncFs = require("fs");
const path = require("path");

function nowIso() {
  return new Date().toISOString();
}

const DEFAULT_DESKTOP_BACKEND_URL = String(process.env.DESKTOP_API_URL || process.env.API_BASE_URL || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
const DEFAULT_PUBLIC_API_BASE_URL = DEFAULT_DESKTOP_BACKEND_URL;

function loadDesktopConfig() {
  const configPath = path.join(__dirname, "..", "config.json");
  try {
    const raw = syncFs.readFileSync(configPath, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {};
  }
}

function defaultSettings() {
  const config = loadDesktopConfig();
  const configuredBackendUrl = String(config.api_url || "").trim();
  const defaultBackendUrl = configuredBackendUrl || DEFAULT_DESKTOP_BACKEND_URL;
  return {
    backendUrl: defaultBackendUrl,
    apiBaseUrl: DEFAULT_PUBLIC_API_BASE_URL,
    backendApi: {
      url: defaultBackendUrl,
      apiToken: "",
      connected: false,
    },
    publicApi: {
      url: DEFAULT_PUBLIC_API_BASE_URL,
      apiToken: "",
      connected: false,
    },
    chromePreviewApiMode: "backend",
    adminUsername: "",
    adminPassword: "",
    tenantId: "default",
    tenantUsername: "",
    tenantPassword: "",
    tenantToken: "",
    backupPath: path.join(__dirname, "..", "backups"),
    backupSchedule: "disabled",
    backupRetention: "7",
    cloudBackupEnabled: "0",
    s3Bucket: "",
    s3Prefix: "football-iptv-backups",
    awsAccessKeyId: "",
    awsSecretAccessKey: "",
    awsRegion: "",
    lastScheduledBackupAt: "",
  };
}

function normalizeSettingsShape(settings = {}) {
  const defaults = defaultSettings();
  const backendApi = {
    ...defaults.backendApi,
    ...(settings.backendApi || {}),
  };
  const publicApi = {
    ...defaults.publicApi,
    ...(settings.publicApi || {}),
  };

  const normalizedBackendUrl = String(
    backendApi.url || settings.backendUrl || defaults.backendApi.url,
  ).trim() || defaults.backendApi.url;
  const normalizedPublicUrl = String(
    publicApi.url || settings.apiBaseUrl || defaults.publicApi.url,
  ).trim() || defaults.publicApi.url;

  return {
    ...defaults,
    ...(settings || {}),
    backendApi: {
      url: normalizedBackendUrl,
      apiToken: String(backendApi.apiToken || "").trim(),
      connected: backendApi.connected === true,
    },
    publicApi: {
      url: normalizedPublicUrl,
      apiToken: String(publicApi.apiToken || "").trim(),
      connected: publicApi.connected === true,
    },
    chromePreviewApiMode: settings.chromePreviewApiMode === "public" ? "public" : "backend",
    backendUrl: normalizedBackendUrl,
    apiBaseUrl: normalizedPublicUrl,
  };
}

class ProviderStore {
  constructor(dbPath) {
    this.storagePath = String(dbPath || "").endsWith(".db")
      ? String(dbPath).replace(/\.db$/i, ".json")
      : `${dbPath}.json`;
    this.state = null;
  }

  async init() {
    await this.#ensureLoaded();
    this.state.settings = normalizeSettingsShape(this.state.settings || {});
    await this.#persist();
  }

  async migrateLegacyProviders(adminId) {
    const normalizedAdminId = String(adminId || "").trim();
    if (!normalizedAdminId) {
      return;
    }
    await this.#ensureLoaded();
    const assigned = this.state.providers.filter((item) => String(item.ownerAdminId || "").trim()).length;
    if (assigned > 0) {
      return;
    }
    const timestamp = nowIso();
    this.state.providers = this.state.providers.map((item) => ({
      ...item,
      ownerAdminId: normalizedAdminId,
      updatedAt: timestamp,
    }));
    await this.#persist();
  }

  async listProviders(adminId) {
    await this.#ensureLoaded();
    const normalizedAdminId = String(adminId || "").trim();
    return this.state.providers
      .filter((item) => String(item.ownerAdminId || "").trim() === normalizedAdminId)
      .sort((left, right) => {
        if (Number(right.isActive || 0) !== Number(left.isActive || 0)) {
          return Number(right.isActive || 0) - Number(left.isActive || 0);
        }
        return String(left.name || "").localeCompare(String(right.name || ""), undefined, { sensitivity: "base" });
      })
      .map((item) => ({ ...item }));
  }

  async listAllProviders() {
    await this.#ensureLoaded();
    return this.state.providers
      .slice()
      .sort((left, right) => String(left.name || "").localeCompare(String(right.name || ""), undefined, { sensitivity: "base" }))
      .map((item) => ({ ...item }));
  }

  async listActiveProviders(adminId = null) {
    const items = adminId == null ? await this.listAllProviders() : await this.listProviders(adminId);
    return items.filter((item) => Number(item.isActive || 0) === 1);
  }

  async getActiveProvider(adminId) {
    const normalizedAdminId = String(adminId || "").trim();
    const providers = await this.listProviders(normalizedAdminId);
    return providers.find((item) => Number(item.isActive || 0) === 1) || null;
  }

  async getProviderById(providerId, adminId = null) {
    await this.#ensureLoaded();
    const normalizedProviderId = Number(providerId || 0);
    if (adminId == null) {
      return this.state.providers.find((item) => item.id === normalizedProviderId) || null;
    }
    const normalizedAdminId = String(adminId || "").trim();
    return this.state.providers.find((item) => item.id === normalizedProviderId && item.ownerAdminId === normalizedAdminId) || null;
  }

  async saveProvider(provider, adminId) {
    const normalizedAdminId = String(adminId || "").trim();
    if (!normalizedAdminId) {
      throw new Error("Admin session required.");
    }
    await this.#ensureLoaded();
    const normalizedProvider = {
      id: provider.id ? Number(provider.id) : null,
      ownerAdminId: normalizedAdminId,
      name: String(provider.name || "").trim(),
      type: provider.type === "m3u" ? "m3u" : "xtream",
      xtreamServerUrl: String(provider.xtreamServerUrl || "").trim(),
      xtreamUsername: String(provider.xtreamUsername || "").trim(),
      xtreamPassword: String(provider.xtreamPassword || "").trim(),
      m3uPlaylistUrl: String(provider.m3uPlaylistUrl || "").trim(),
      cacheTtlSeconds: Number(provider.cacheTtlSeconds || 300),
      isActive: provider.isActive ? 1 : 0,
    };

    if (!normalizedProvider.name) {
      throw new Error("Provider name is required.");
    }

    if (normalizedProvider.type === "xtream") {
      if (!normalizedProvider.xtreamServerUrl || !normalizedProvider.xtreamUsername || !normalizedProvider.xtreamPassword) {
        throw new Error("Xtream providers need server URL, username, and password.");
      }
      normalizedProvider.m3uPlaylistUrl = "";
    } else if (!normalizedProvider.m3uPlaylistUrl) {
      throw new Error("M3U providers need a playlist URL.");
    } else {
      normalizedProvider.xtreamServerUrl = "";
      normalizedProvider.xtreamUsername = "";
      normalizedProvider.xtreamPassword = "";
    }

    if (normalizedProvider.isActive) {
      this.state.providers = this.state.providers.map((item) => (
        item.ownerAdminId === normalizedAdminId
          ? { ...item, isActive: 0, updatedAt: nowIso() }
          : item
      ));
    }

    const timestamp = nowIso();
    if (normalizedProvider.id) {
      const index = this.state.providers.findIndex((item) => item.id === normalizedProvider.id && item.ownerAdminId === normalizedAdminId);
      if (index === -1) {
        throw new Error("Provider not found.");
      }
      this.state.providers[index] = {
        ...this.state.providers[index],
        ...normalizedProvider,
        updatedAt: timestamp,
      };
      await this.#persist();
      return { ...this.state.providers[index] };
    }

    const nextId = this.state.providers.reduce((maxId, item) => Math.max(maxId, Number(item.id || 0)), 0) + 1;
    const created = {
      ...normalizedProvider,
      id: nextId,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.state.providers.push(created);
    await this.#persist();
    return { ...created };
  }

  async deleteProvider(providerId, adminId) {
    await this.#ensureLoaded();
    const normalizedAdminId = String(adminId || "").trim();
    const normalizedProviderId = Number(providerId || 0);
    this.state.providers = this.state.providers.filter((item) => !(item.id === normalizedProviderId && item.ownerAdminId === normalizedAdminId));
    await this.#persist();
  }

  async setActiveProvider(providerId, adminId) {
    await this.#ensureLoaded();
    const normalizedAdminId = String(adminId || "").trim();
    const normalizedProviderId = Number(providerId || 0);
    const timestamp = nowIso();
    let found = false;
    this.state.providers = this.state.providers.map((item) => {
      if (item.ownerAdminId !== normalizedAdminId) {
        return item;
      }
      if (item.id === normalizedProviderId) {
        found = true;
        return { ...item, isActive: 1, updatedAt: timestamp };
      }
      return { ...item, isActive: 0, updatedAt: timestamp };
    });
    if (!found) {
      throw new Error("Provider not found.");
    }
    await this.#persist();
  }

  async saveSettings(settings) {
    await this.#ensureLoaded();
    this.state.settings = normalizeSettingsShape({
      ...(this.state.settings || {}),
      ...(settings || {}),
    });
    await this.#persist();
  }

  async getSettings() {
    await this.#ensureLoaded();
    return normalizeSettingsShape(this.state.settings || {});
  }

  getStoragePath() {
    return this.storagePath;
  }

  async reload() {
    this.state = null;
    await this.#ensureLoaded();
  }

  async #ensureLoaded() {
    if (this.state) {
      return;
    }
    const parentDir = path.dirname(this.storagePath);
    await fs.mkdir(parentDir, { recursive: true });
    try {
      const raw = await fs.readFile(this.storagePath, "utf8");
      const parsed = JSON.parse(raw);
      this.state = {
        providers: Array.isArray(parsed?.providers) ? parsed.providers.map((item) => ({ ...item })) : [],
        settings: parsed?.settings && typeof parsed.settings === "object" ? { ...parsed.settings } : {},
      };
    } catch (_) {
      this.state = {
        providers: [],
        settings: {},
      };
      await this.#persist();
    }
  }

  async #persist() {
    await fs.mkdir(path.dirname(this.storagePath), { recursive: true });
    await fs.writeFile(
      this.storagePath,
      JSON.stringify({
        providers: this.state.providers,
        settings: this.state.settings,
      }, null, 2),
      "utf8",
    );
  }
}

module.exports = {
  ProviderStore,
};
