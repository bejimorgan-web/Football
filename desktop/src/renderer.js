const state = {
  providers: [],
  activeProvider: null,
  selectedProviderId: null,
  settings: {
    backendUrl: "http://127.0.0.1:8000",
    apiBaseUrl: "http://127.0.0.1:8000",
    backendApi: { url: "http://127.0.0.1:8000", apiToken: "", connected: false },
    publicApi: { url: "http://127.0.0.1:8000", apiToken: "", connected: false },
    chromePreviewApiMode: "backend",
    adminUsername: "",
    adminPassword: "",
    tenantId: "default",
    tenantUsername: "",
    tenantPassword: "",
    tenantToken: "",
    backupPath: "",
    backupSchedule: "disabled",
    backupRetention: "7",
    cloudBackupEnabled: "0",
    s3Bucket: "",
    s3Prefix: "football-iptv-backups",
    awsRegion: "",
  },
  tenants: [],
  branding: null,
  setup: { setup_completed: true, steps: [], mobile_api_token: "", server_id: "" },
  session: {},
  runtimeStatus: null,
  backup: { configured: null, python: { available: false }, backups: [], recent_logs: [], task_logs: [] },
  activeProviders: [],
  nations: [],
  competitions: [],
  competitionClubLinks: [],
  clubs: [],
  streams: [],
  approvedMatches: [],
  users: [],
  onlineUsers: [],
  userStats: { total_users: 0, trial_users: 0, active_users: 0, blocked_users: 0, live_viewers: 0 },
  analytics: { live: { live_viewers: 0, streams: [], competitions: [] }, streams: [], topMatches: [], topCompetitions: [], dailyViewers: [], countries: [] },
  masterLive: { status: "idle", version: null, streams: { items: [] }, liveScores: { matches: [] }, standings: { standings: [] }, fixtures: { matches: [] }, lastUpdatedAt: "", error: "" },
  platformClients: { items: [], stats: {}, audit_logs: [] },
  security: { flagged_devices: [], vpn_users: [], suspicious_ip_changes: [], blocked_devices: [], active_sessions: [], security_logs: [] },
  mobileBuilder: {
    history: [],
    latest: null,
    activeBuildId: "",
    status: { status: "idle", progress: 0, version: "", artifact_name: "", error: "", logs: "" },
    preflight: { ready: null, checks: [], artifact_storage: "", worker_enabled_on_host: false },
  },
  apkManagement: { items: [], latest: null },
  updateInfo: { history: [], latest: null, dismissed: false, state: { status: "idle", currentVersion: "" } },
  groups: [],
  selectedStreamProviderId: null,
  selectedNationId: null,
  selectedCompetitionId: null,
  selectedGroup: null,
  selectedChannel: null,
  activeSection: "dashboard",
  activeCatalogTab: "nations",
};

let mobileBuildLogsShouldAutoScroll = true;
let mobileBuildLogsHiddenSnapshot = "";

const DEFAULT_API_URL = "http://127.0.0.1:8000";

function isDevelopmentMode() {
  try {
    const hostname = String(window.location?.hostname || "").trim().toLowerCase();
    const protocol = String(window.location?.protocol || "").trim().toLowerCase();
    return protocol === "file:" || hostname === "" || hostname === "localhost" || hostname === "127.0.0.1";
  } catch (_) {
    return true;
  }
}

function forceResetConfig() {
  try {
    window.localStorage?.clear();
  } catch (_) {
    // Ignore storage access errors and keep the in-memory localhost fallback.
  }
}

if (isDevelopmentMode()) {
  forceResetConfig();
}

let hls;
let dailyViewersChart;
let competitionPopularityChart;
let dashboardPollIntervalId = null;
let dashboardPollInFlight = false;
const isMasterRole = () => String(state.session?.role || "").toLowerCase() === "master";
const isClientRole = () => !isMasterRole();
const mobileAppAlreadyGenerated = () => state.branding?.mobile_app_generated === true;
const DEFAULT_LOGO_SRC = "./default-logo.svg";

function effectiveTenantId() {
  const sessionTenantId = String(state.session?.tenantId || "").trim();
  const settingsTenantId = String(state.settings?.tenantId || "").trim();
  if (isMasterRole()) {
    if (settingsTenantId && settingsTenantId.toLowerCase() !== "default") {
      return settingsTenantId;
    }
    return sessionTenantId || "master";
  }
  return sessionTenantId || settingsTenantId || "default";
}

const $ = (id) => document.getElementById(id);
const getNodes = (...ids) => ids.map((id) => $(id)).filter(Boolean);

const el = {
  navItems: [...document.querySelectorAll(".nav-item")],
  views: [...document.querySelectorAll(".view")],
  navTargets: [...document.querySelectorAll("[data-nav-target]")],
  masterOnly: [...document.querySelectorAll(".master-only")],
  catalogTabs: [...document.querySelectorAll(".tab-button")],
  catalogPanels: [...document.querySelectorAll(".catalog-panel")],
  workspaceTitle: $("workspaceTitle"),
  workspaceSubtitle: $("workspaceSubtitle"),
  welcomeClientLabel: $("welcomeClientLabel"),
  headerSubscriptionLabel: $("headerSubscriptionLabel"),
  headerPlanLabel: $("headerPlanLabel"),
  headerServerLabel: $("headerServerLabel"),
  openProviderManagerButton: $("openProviderManagerButton"),
  openProviderManagerButtonDuplicate: $("openProviderManagerButtonDuplicate"),
  backupNowButton: $("backupNowButton"),
  setupWizardCard: $("setupWizardCard"),
  setupStepList: $("setupStepList"),
  setupMobileToken: $("setupMobileToken"),
  setupServerId: $("setupServerId"),
  completeSetupButton: $("completeSetupButton"),
  refreshStreamsButton: $("refreshStreamsButton"),
  syncProviderButton: $("syncProviderButton"),
  refreshUsersButton: $("refreshUsersButton"),
  refreshAnalyticsButton: $("refreshAnalyticsButton"),
  analyticsRefreshButtonDuplicate: $("analyticsRefreshButtonDuplicate"),
  refreshSecurityButton: $("refreshSecurityButton"),
  openWhiteLabelDashboardButton: $("openWhiteLabelDashboardButton"),
  manualUpdateCheckButton: $("manualUpdateCheckButton"),
  desktopVersionLabel: $("desktopVersionLabel"),
  footerDesktopVersion: $("footerDesktopVersion"),
  updateStatusBadge: $("updateStatusBadge"),
  updateLatestVersionLabel: $("updateLatestVersionLabel"),
  updateMandatoryLabel: $("updateMandatoryLabel"),
  updateReleaseDateLabel: $("updateReleaseDateLabel"),
  updateReleaseNotesLabel: $("updateReleaseNotesLabel"),
  updateProgressBar: $("updateProgressBar"),
  updateProgressLabel: $("updateProgressLabel"),
  updatePrimaryButton: $("updatePrimaryButton"),
  updateSecondaryButton: $("updateSecondaryButton"),
  updateOverlay: $("updateOverlay"),
  publishUpdateForm: $("publishUpdateForm"),
  updateVersionInput: $("updateVersionInput"),
  updateInstallerInput: $("updateInstallerInput"),
  updateReleaseNotesInput: $("updateReleaseNotesInput"),
  updateMandatoryInput: $("updateMandatoryInput"),
  latestPublishedVersionLabel: $("latestPublishedVersionLabel"),
  latestPublishedDateLabel: $("latestPublishedDateLabel"),
  latestPublishedDownloadLabel: $("latestPublishedDownloadLabel"),
  latestPublishedMandatoryLabel: $("latestPublishedMandatoryLabel"),
  updateHistoryTable: $("updateHistoryTable"),
  providerModal: $("providerModal"),
  closeProviderModalButton: $("closeProviderModalButton"),
  providerList: $("providerList"),
  providerForm: $("providerForm"),
  providerIdInput: $("providerIdInput"),
  providerNameInput: $("providerNameInput"),
  providerTypeSelect: $("providerTypeSelect"),
  xtreamServerUrlInput: $("xtreamServerUrlInput"),
  xtreamUsernameInput: $("xtreamUsernameInput"),
  xtreamPasswordInput: $("xtreamPasswordInput"),
  m3uPlaylistUrlInput: $("m3uPlaylistUrlInput"),
  cacheTtlInput: $("cacheTtlInput"),
  providerActiveCheckbox: $("providerActiveCheckbox"),
  deleteProviderButton: $("deleteProviderButton"),
  newProviderButton: $("newProviderButton"),
  backendApiUrlInput: $("backendApiUrlInput"),
  backendApiTokenInput: $("backendApiTokenInput"),
  backendApiState: $("backendApiState"),
  backendApiConnectButton: $("backendApiConnectButton"),
  backendApiDisconnectButton: $("backendApiDisconnectButton"),
  backendApiTestButton: $("backendApiTestButton"),
  publicApiUrlInput: $("publicApiUrlInput"),
  publicApiTokenInput: $("publicApiTokenInput"),
  publicApiState: $("publicApiState"),
  publicApiConnectButton: $("publicApiConnectButton"),
  publicApiDisconnectButton: $("publicApiDisconnectButton"),
  publicApiTestButton: $("publicApiTestButton"),
  chromePreviewApiToggle: $("chromePreviewApiToggle"),
  adminUsernameInput: $("adminUsernameInput"),
  adminPasswordInput: $("adminPasswordInput"),
  tenantSelect: $("tenantSelect"),
  tenantUsernameInput: $("tenantUsernameInput"),
  tenantPasswordInput: $("tenantPasswordInput"),
  saveBackendSettingsButton: $("saveBackendSettingsButton"),
  tenantLoginButton: $("tenantLoginButton"),
  settingsBackendUrlMirror: $("settingsBackendUrlMirror"),
  settingsTenantMirror: $("settingsTenantMirror"),
  settingsTenantUserMirror: $("settingsTenantUserMirror"),
  saveBrandingButton: $("saveBrandingButton"),
  brandingAppNameInput: $("brandingAppNameInput"),
  brandingPrimaryColorInput: $("brandingPrimaryColorInput"),
  brandingAccentColorInput: $("brandingAccentColorInput"),
  brandingSecondaryColorInput: $("brandingSecondaryColorInput"),
  brandingSurfaceColorInput: $("brandingSurfaceColorInput"),
  brandingBackgroundColorInput: $("brandingBackgroundColorInput"),
  brandingTextColorInput: $("brandingTextColorInput"),
  brandingLogoFileInput: $("brandingLogoFileInput"),
  brandingIconFileInput: $("brandingIconFileInput"),
  mobileBuilderAppNameInput: $("mobileBuilderAppNameInput"),
  mobileBuilderPackageInput: $("mobileBuilderPackageInput"),
  mobileBuilderServerUrlInput: $("mobileBuilderServerUrlInput"),
  mobileBuilderPrimaryColorInput: $("mobileBuilderPrimaryColorInput"),
  mobileBuilderSecondaryColorInput: $("mobileBuilderSecondaryColorInput"),
  mobileBuilderTenantIdLabel: $("mobileBuilderTenantIdLabel"),
  mobileBuilderLogoInput: $("mobileBuilderLogoInput"),
  mobileBuilderSplashInput: $("mobileBuilderSplashInput"),
  saveMobileAppSettingsButton: $("saveMobileAppSettingsButton"),
  generateMobileApkButton: $("generateMobileApkButton"),
  cancelMobileBuildButton: $("cancelMobileBuildButton"),
  refreshMobileBuildsButton: $("refreshMobileBuildsButton"),
  clearMobileBuildPreflightButton: $("clearMobileBuildPreflightButton"),
  refreshMobileBuildPreflightButton: $("refreshMobileBuildPreflightButton"),
  mobileBuildStatusLabel: $("mobileBuildStatusLabel"),
  mobileBuildProgressText: $("mobileBuildProgressText"),
  mobileBuildVersionLabel: $("mobileBuildVersionLabel"),
  mobileBuildArtifactLabel: $("mobileBuildArtifactLabel"),
  mobileBuildProgressBar: $("mobileBuildProgressBar"),
  mobileBuildErrorLabel: $("mobileBuildErrorLabel"),
  mobileBuildPreflightSummary: $("mobileBuildPreflightSummary"),
  mobileBuildPreflightOutput: $("mobileBuildPreflightOutput"),
  mobileBuildAuthSummary: $("mobileBuildAuthSummary"),
  mobileBuildAuthOutput: $("mobileBuildAuthOutput"),
  mobileBuildLogsOutput: $("mobileBuildLogsOutput"),
  clearMobileBuildLogsButton: $("clearMobileBuildLogsButton"),
  copyMobileBuildLogsButton: $("copyMobileBuildLogsButton"),
  downloadMobileBuildLogsButton: $("downloadMobileBuildLogsButton"),
  mobileBuildLockMessage: $("mobileBuildLockMessage"),
  mobileBuildHistoryTable: $("mobileBuildHistoryTable"),
  apkVersionInput: $("apkVersionInput"),
  apkFileInput: $("apkFileInput"),
  apkForceUpdateInput: $("apkForceUpdateInput"),
  uploadApkButton: $("uploadApkButton"),
  latestApkVersionLabel: $("latestApkVersionLabel"),
  latestApkPathLabel: $("latestApkPathLabel"),
  latestApkForceLabel: $("latestApkForceLabel"),
  apkManagementTable: $("apkManagementTable"),
  saveBackupSettingsButton: $("saveBackupSettingsButton"),
  refreshBackupButton: $("refreshBackupButton"),
  backupPathInput: $("backupPathInput"),
  backupScheduleSelect: $("backupScheduleSelect"),
  backupRetentionInput: $("backupRetentionInput"),
  cloudBackupEnabledInput: $("cloudBackupEnabledInput"),
  s3BucketInput: $("s3BucketInput"),
  s3PrefixInput: $("s3PrefixInput"),
  awsRegionInput: $("awsRegionInput"),
  pythonRuntimeLabel: $("pythonRuntimeLabel"),
  backupLastRunLabel: $("backupLastRunLabel"),
  backupRuntimeMirror: $("backupRuntimeMirror"),
  backupLastRunMirror: $("backupLastRunMirror"),
  backupCountLabel: $("backupCountLabel"),
  activeProviderLabel: $("activeProviderLabel"),
  totalUsersLabel: $("totalUsersLabel"),
  trialUsersLabel: $("trialUsersLabel"),
  activeUsersLabel: $("activeUsersLabel"),
  blockedUsersLabel: $("blockedUsersLabel"),
  liveViewersLabel: $("liveViewersLabel"),
  nationCountLabel: $("nationCountLabel"),
  competitionCountLabel: $("competitionCountLabel"),
  approvedCountLabel: $("approvedCountLabel"),
  analyticsLiveViewersLabels: getNodes("analyticsLiveViewersLabel", "analyticsLiveViewersLabelDuplicate"),
  analyticsActiveStreamsLabels: getNodes("analyticsActiveStreamsLabel", "analyticsActiveStreamsLabelDuplicate"),
  analyticsCompetitionsLabels: getNodes("analyticsCompetitionsLabel", "analyticsCompetitionsLabelDuplicate"),
  analyticsRefreshLabel: $("analyticsRefreshLabel"),
  analyticsStreamsLists: getNodes("analyticsStreamsList", "analyticsStreamsListDuplicate"),
  masterLiveUpdatedLabel: $("masterLiveUpdatedLabel"),
  masterLiveVersionLabel: $("masterLiveVersionLabel"),
  masterLiveStreamsLabel: $("masterLiveStreamsLabel"),
  masterLiveScoresLabel: $("masterLiveScoresLabel"),
  masterLiveList: $("masterLiveList"),
  analyticsTopMatchesList: $("analyticsTopMatchesList"),
  analyticsTopCompetitionsList: $("analyticsTopCompetitionsList"),
  analyticsCountriesList: $("analyticsCountriesList"),
  dailyViewersChart: $("dailyViewersChart"),
  competitionPopularityChart: $("competitionPopularityChart"),
  userCountCaption: $("userCountCaption"),
  onlineCountCaption: $("onlineCountCaption"),
  userList: $("userList"),
  onlineUserList: $("onlineUserList"),
  nationList: $("nationList"),
  competitionList: $("competitionList"),
  clubList: $("clubList"),
  catalogNationList: $("catalogNationList"),
  catalogCompetitionList: $("catalogCompetitionList"),
  catalogClubList: $("catalogClubList"),
  newNationButton: $("newNationButton"),
  newCompetitionButton: $("newCompetitionButton"),
  newClubButton: $("newClubButton"),
  catalogNewNationButton: $("catalogNewNationButton"),
  catalogNewCompetitionButton: $("catalogNewCompetitionButton"),
  catalogNewClubButton: $("catalogNewClubButton"),
  groupSummary: $("groupSummary"),
  streamProviderSelect: $("streamProviderSelect"),
  groupList: $("groupList"),
  channelList: $("channelList"),
  channelPaneSubtitle: $("channelPaneSubtitle"),
  approvalSelectedStream: $("approvalSelectedStream"),
  approveForm: $("approveForm"),
  approveNationSelect: $("approveNationSelect"),
  approveCompetitionSelect: $("approveCompetitionSelect"),
  approveHomeClubSelect: $("approveHomeClubSelect"),
  approveAwayClubSelect: $("approveAwayClubSelect"),
  approveKickoffInput: $("approveKickoffInput"),
  approveCompetitionLogoPreview: $("approveCompetitionLogoPreview"),
  approveCompetitionNamePreview: $("approveCompetitionNamePreview"),
  approveHomeClubLogoPreview: $("approveHomeClubLogoPreview"),
  approveHomeClubNamePreview: $("approveHomeClubNamePreview"),
  approveAwayClubLogoPreview: $("approveAwayClubLogoPreview"),
  approveAwayClubNamePreview: $("approveAwayClubNamePreview"),
  approvePreviewLabel: $("approvePreviewLabel"),
  videoPreview: $("preview-player"),
  previewOverlay: $("previewOverlay"),
  previewTitle: $("previewTitle"),
  previewGroup: $("previewGroup"),
  previewId: $("previewId"),
  previewCompetition: $("previewCompetition"),
  approveChannelButton: $("approveChannelButton"),
  removeApprovedButton: $("removeApprovedButton"),
  approvedList: $("approvedList"),
  backupList: $("backupList"),
  backupLogLists: getNodes("backupLogList", "backupLogListDuplicate"),
  platformClientsTotalLabel: $("platformClientsTotalLabel"),
  platformClientsActiveLabel: $("platformClientsActiveLabel"),
  platformClientsTrialLabel: $("platformClientsTrialLabel"),
  platformClientsBlockedLabel: $("platformClientsBlockedLabel"),
  platformClientsExpiredLabel: $("platformClientsExpiredLabel"),
  platformClientsTable: $("platformClientsTable"),
  refreshPlatformClientsButton: $("refreshPlatformClientsButton"),
  systemLogsTable: $("systemLogsTable"),
  providerWorkspaceList: $("providerWorkspaceList"),
  securityFlaggedCount: $("securityFlaggedCount"),
  securityVpnCount: $("securityVpnCount"),
  securityBlockedCount: $("securityBlockedCount"),
  securityFlaggedLists: getNodes("securityFlaggedList", "securityFlaggedListDuplicate"),
  securityVpnList: $("securityVpnList"),
  securityBlockedList: $("securityBlockedList"),
  securityIpList: $("securityIpList"),
  securityLogsList: $("securityLogsList"),
  serverStatusPanel: $("serverStatusPanel"),
  entityModal: $("entityModal"),
  closeEntityModalButton: $("closeEntityModalButton"),
  entityModalEyebrow: $("entityModalEyebrow"),
  entityModalTitle: $("entityModalTitle"),
  entityForm: $("entityForm"),
  entityIdInput: $("entityIdInput"),
  entityTypeInput: $("entityTypeInput"),
  entityNameInput: $("entityNameInput"),
  entityNationField: $("entityNationField"),
  entityNationSelect: $("entityNationSelect"),
  entityCompetitionTypeField: $("entityCompetitionTypeField"),
  entityCompetitionTypeSelect: $("entityCompetitionTypeSelect"),
  entityCompetitionParticipantField: $("entityCompetitionParticipantField"),
  entityCompetitionParticipantSelect: $("entityCompetitionParticipantSelect"),
  entityCompetitionClubAssignmentsField: $("entityCompetitionClubAssignmentsField"),
  entityCompetitionClubAssignments: $("entityCompetitionClubAssignments"),
  entityClubCompetitionField: $("entityClubCompetitionField"),
  entityClubCompetitionSelect: $("entityClubCompetitionSelect"),
  entityLogoFileInput: $("entityLogoFileInput"),
  entityLogoPreview: $("entityLogoPreview"),
  deleteEntityButton: $("deleteEntityButton"),
  toast: $("toast"),
};

const html = (value) => String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
const metric = (nodes, value) => [].concat(nodes).filter(Boolean).forEach((node) => { node.textContent = String(value ?? 0); });
const isValidHttpUrl = (value) => {
  try {
    const parsed = new URL(String(value || "").trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (_) {
    return false;
  }
};
const endpointConfig = (kind) => {
  const endpointState = kind === "public" ? state.settings.publicApi : state.settings.backendApi;
  return {
    url: String(endpointState?.url || "").trim() || DEFAULT_API_URL,
    apiToken: String(endpointState?.apiToken || "").trim(),
    connected: endpointState?.connected === true,
  };
};
const previewApiConfig = () => endpointConfig("backend");
const assetUrl = (url) => {
  const value = String(url || "").trim();
  if (!value) return "";
  if (/^https?:\/\//i.test(value) || value.startsWith("data:")) return value;
  const backendBase = String(previewApiConfig().url || "").trim().replace(/\/+$/, "");
  if (!backendBase) return value;
  const resolved = value.startsWith("/") ? `${backendBase}${value}` : `${backendBase}/${value}`;
  return /^https?:\/\//i.test(resolved) ? resolved : "";
};
const safeLogoUrl = (url) => assetUrl(url) || DEFAULT_LOGO_SRC;
const approvedMap = () => new Map(state.approvedMatches.map((item) => [String(item.stream_id), item]));

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizeNationItem(item = {}) {
  return {
    ...item,
    id: String(item.id || ""),
    name: String(item.name || ""),
    logo_url: String(item.logo_url || ""),
  };
}

function normalizeCompetitionItem(item = {}) {
  return {
    ...item,
    id: String(item.id || ""),
    name: String(item.name || ""),
    nation_id: String(item.nation_id || ""),
    type: String(item.type || "league"),
    participant_type: String(item.participant_type || "club"),
    club_ids: asArray(item.club_ids).map((clubId) => String(clubId || "")).filter(Boolean),
    logo_url: String(item.logo_url || ""),
  };
}

function normalizeClubItem(item = {}) {
  return {
    ...item,
    id: String(item.id || ""),
    name: String(item.name || ""),
    nation_id: String(item.nation_id || ""),
    competition_ids: asArray(item.competition_ids).map((competitionId) => String(competitionId || "")).filter(Boolean),
    logo_url: String(item.logo_url || ""),
  };
}

function normalizeCompetitionClubLink(item = {}) {
  return {
    competition_id: String(item.competition_id || ""),
    club_ids: asArray(item.club_ids).map((clubId) => String(clubId || "")).filter(Boolean),
  };
}

function getCompetitionClubLink(competitionId) {
  const normalizedCompetitionId = String(competitionId || "").trim();
  if (!normalizedCompetitionId) return null;
  return state.competitionClubLinks.find((item) => item.competition_id === normalizedCompetitionId) || null;
}

function getVisibleClubsForCompetition(competitionId) {
  const normalizedCompetitionId = String(competitionId || "").trim();
  if (!normalizedCompetitionId) return [];
  const link = getCompetitionClubLink(normalizedCompetitionId);
  if (!link) return [];
  return state.clubs.filter((club) => link.club_ids.includes(String(club.id || "")));
}

function applyCatalogState({ nations = [], competitions = [], competitionClubLinks = [], clubs = [] } = {}) {
  state.nations = asArray(nations).map(normalizeNationItem);
  state.competitions = asArray(competitions).map(normalizeCompetitionItem);
  state.competitionClubLinks = asArray(competitionClubLinks).map(normalizeCompetitionClubLink);
  state.clubs = asArray(clubs).map(normalizeClubItem);

  if (!state.selectedNationId || !state.nations.find((item) => item.id === state.selectedNationId)) {
    state.selectedNationId = state.nations[0]?.id || null;
  }

  const visibleCompetitions = state.selectedNationId
    ? state.competitions.filter((item) => item.nation_id === state.selectedNationId)
    : state.competitions;
  if (state.selectedCompetitionId && !visibleCompetitions.find((item) => item.id === state.selectedCompetitionId)) {
    state.selectedCompetitionId = null;
  }
}

function compactPayload(payload = {}) {
  const result = {};
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      result[key] = value
        .map((item) => String(item || "").trim())
        .filter(Boolean);
      continue;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) continue;
      result[key] = trimmed;
      continue;
    }
    result[key] = value;
  }
  return result;
}

function upsertCatalogStateItem(type, item) {
  if (!item || typeof item !== "object") return;
  if (type === "nation") {
    const nextItem = normalizeNationItem(item);
    state.nations = state.nations.some((entry) => entry.id === nextItem.id)
      ? state.nations.map((entry) => (entry.id === nextItem.id ? nextItem : entry))
      : [...state.nations, nextItem];
    return;
  }
  if (type === "competition") {
    const nextItem = normalizeCompetitionItem(item);
    state.competitions = state.competitions.some((entry) => entry.id === nextItem.id)
      ? state.competitions.map((entry) => (entry.id === nextItem.id ? nextItem : entry))
      : [...state.competitions, nextItem];
    return;
  }
  if (type === "club") {
    const nextItem = normalizeClubItem(item);
    state.clubs = state.clubs.some((entry) => entry.id === nextItem.id)
      ? state.clubs.map((entry) => (entry.id === nextItem.id ? nextItem : entry))
      : [...state.clubs, nextItem];
  }
}

function removeCatalogStateItem(type, id) {
  const normalizedId = String(id || "");
  if (type === "nation") {
    state.nations = state.nations.filter((item) => item.id !== normalizedId);
    return;
  }
  if (type === "competition") {
    state.competitions = state.competitions.filter((item) => item.id !== normalizedId);
    return;
  }
  if (type === "club") {
    state.clubs = state.clubs.filter((item) => item.id !== normalizedId);
  }
}

function normalizeProviderGroups(groups, streams) {
  if (Array.isArray(groups) && groups.length && typeof groups[0] === "object") {
    return groups.map((group) => ({
      id: String(group.id || group.group_id || group.name || ""),
      name: String(group.name || group.group_name || "Ungrouped"),
      channels: Array.isArray(group.channels) ? group.channels.map((channel) => ({
        ...channel,
        id: String(channel.id || channel.stream_id || ""),
        stream_id: String(channel.stream_id || channel.id || ""),
        name: String(channel.name || channel.channel_name || "Unnamed channel"),
        group_id: String(channel.group_id || group.id || group.group_id || ""),
      })) : [],
    }));
  }

  const streamItems = Array.isArray(streams) ? streams : [];
  const grouped = new Map();
  for (const stream of streamItems) {
    const name = String(stream.group || "Ungrouped");
    const id = name.toLowerCase().replace(/\s+/g, "-");
    if (!grouped.has(id)) grouped.set(id, { id, name, channels: [] });
    grouped.get(id).channels.push({
      ...stream,
      id: String(stream.id || stream.stream_id || ""),
      stream_id: String(stream.stream_id || stream.id || ""),
      name: String(stream.name || stream.raw_name || "Unnamed channel"),
      group_id: id,
    });
  }
  return [...grouped.values()].sort((left, right) => left.name.localeCompare(right.name));
}

function showToast(message, isError = false) {
  el.toast.textContent = message;
  el.toast.classList.remove("hidden", "error");
  el.toast.classList.toggle("error", isError);
  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = setTimeout(() => el.toast.classList.add("hidden"), 3200);
}

async function fetchBackendConnectivitySnapshot() {
  const backendUrl = String(previewApiConfig().url || "").trim() || DEFAULT_API_URL;
  const readJson = async (path) => {
    const response = await fetch(`${backendUrl}${path}`);
    if (!response.ok) {
      throw new Error(`${path} returned ${response.status}`);
    }
    return response.json();
  };

  try {
    const [streams, analytics, liveMatches] = await Promise.all([
      readJson("/streams"),
      readJson("/analytics/live"),
      readJson("/football/live"),
    ]);
    console.log("Backend connectivity snapshot", { streams, analytics, liveMatches });
  } catch (error) {
    console.warn("Backend connectivity probe failed", error);
  }
}

function setModalVisibility(modal, visible) {
  modal.classList.toggle("hidden", !visible);
}

function optionMarkup(items, selected = "", includeEmpty = false) {
  const rows = includeEmpty ? ["<option value=\"\">Not set</option>"] : [];
  for (const item of items) rows.push(`<option value="${item.id}" ${item.id === selected ? "selected" : ""}>${html(item.name)}</option>`);
  return rows.join("");
}

function logoMarkup(url, label, large = false) {
  const klass = `logo-avatar${large ? " large" : ""}`;
  const resolvedLogoUrl = safeLogoUrl(url);
  return `<div class="${klass}"><img src="${resolvedLogoUrl}" alt="${html(label)}" onerror="this.onerror=null;this.src='${DEFAULT_LOGO_SRC}'"></div>`;
}

function firstLogoValue(...values) {
  for (const value of values) {
    const normalized = String(value || "").trim();
    if (normalized) return normalized;
  }
  return "";
}

function approvedMatchLogoMarkup(match) {
  const homeLogoUrl = firstLogoValue(match.home_club_logo, match.home_team_logo, match.home_logo, match.stream_logo);
  const awayLogoUrl = firstLogoValue(match.away_club_logo, match.away_team_logo, match.away_logo, match.stream_logo);
  const competitionLogoUrl = firstLogoValue(match.competition_logo, match.logo, match.nation_logo, match.stream_logo);
  const homeLogo = logoMarkup(homeLogoUrl, match.home_club_name || match.home_team_name || "Home");
  const awayLogo = logoMarkup(awayLogoUrl, match.away_club_name || match.away_team_name || "Away");
  const competitionLogo = `<div class="approved-competition-logo" title="${html(match.competition_name || "Competition")}">${logoMarkup(competitionLogoUrl, match.competition_name || "Competition")}</div>`;
  return `<div class="approved-match-logos">${homeLogo}<span class="approved-logo-separator">vs</span>${awayLogo}${competitionLogo}</div>`;
}

function paintLogo(node, url, label) {
  node.innerHTML = logoMarkup(url, label, node.classList.contains("large"));
}

function statusPill(status) {
  const value = String(status || "unknown").toLowerCase();
  const tone = value === "active" ? "active" : value === "trial" ? "warning" : value === "free" ? "free" : ["blocked", "expired", "device_blocked", "insecure_device", "vpn_blocked"].includes(value) ? "danger" : "";
  return `<span class="pill ${tone}">${html(value)}</span>`;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function setActiveSection(section = "dashboard") {
  state.activeSection = section;
  const titles = isMasterRole()
    ? {
        dashboard: ["Dashboard", "Monitor platform health, master operations, and white-label activity from one workspace."],
        streams: ["Streams", "Manage the master provider, stream approvals, and the master streaming catalog."],
        catalog: ["Football Catalog", "Manage the master nations, competitions, clubs, and logos."],
        providers: ["Providers", "Manage the master IPTV provider credentials and active ingestion source."],
        analytics: ["Analytics", "Track live viewers, top matches, active users, and master audience trends."],
        branding: ["Branding", "Manage the master app identity, assets, and platform branding values."],
        mobile_builder: ["Mobile App Settings", "Configure the master mobile app once, then push branding updates dynamically."],
        users: ["Users", "Control device access, subscriptions, free access, and live session visibility."],
        platform_clients: ["Platform Clients", "Manage client accounts, subscriptions, trials, and server bindings."],
        system_logs: ["System Logs", "Inspect audit activity across protected admin APIs and tools."],
        security: ["Security", "Review VPN usage, suspicious IP changes, blocked devices, and sharing signals."],
        backups: ["Backups", "Backups, restore history, scheduling, retention, and cloud backup controls."],
      }
    : {
        dashboard: ["Dashboard", "Monitor streams, approvals, users, security, and system health from one workspace."],
        streams: ["Streams", "Four-panel workflow for football catalog selection, provider groups, approval, and preview."],
        catalog: ["Football Catalog", "Manage nations, competitions, clubs, and logos used in match approval."],
        providers: ["Providers", "Manage IPTV provider credentials and choose the active ingestion source."],
        analytics: ["Analytics", "Track live viewers, top matches, active users, and audience trends."],
        branding: ["Branding", "Manage app identity, asset uploads, and platform-client theme colors."],
        mobile_builder: ["Mobile App Settings", "Configure the tenant mobile app once, then refresh branding dynamically without rebuilding."],
        users: ["Users", "Control device access, subscriptions, free access, and live session visibility."],
        security: ["Security", "Review VPN usage, suspicious IP changes, blocked devices, and sharing signals."],
        backups: ["Backups", "Backups, restore history, scheduling, retention, and cloud backup controls."],
      };
  if (!titles[section]) section = "dashboard";
  el.navItems.forEach((item) => item.classList.toggle("active", item.dataset.section === section));
  el.views.forEach((view) => view.classList.toggle("active", view.dataset.view === section));
  el.workspaceTitle.textContent = titles[section][0];
  el.workspaceSubtitle.textContent = titles[section][1];
}

function applyRoleAccess() {
  const master = isMasterRole();
  el.masterOnly.forEach((node) => node.classList.toggle("hidden", !master));
  document.querySelectorAll(".role-master, .role-client").forEach((node) => {
    const visibleForMaster = node.classList.contains("role-master");
    const visibleForClient = node.classList.contains("role-client");
    node.classList.toggle("hidden", master ? !visibleForMaster : !visibleForClient);
  });
  if (master && ["settings"].includes(state.activeSection)) setActiveSection("dashboard");
  if (!master && ["platform_clients", "system_logs", "security", "users", "backups", "settings"].includes(state.activeSection)) setActiveSection("dashboard");
}

function setCatalogTab(tab = "nations") {
  state.activeCatalogTab = tab;
  el.catalogTabs.forEach((button) => button.classList.toggle("active", button.dataset.catalogTab === tab));
  el.catalogPanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.catalogPanel === tab));
}

function updateProviderTypeVisibility() {
  const isXtream = el.providerTypeSelect.value === "xtream";
  document.querySelectorAll(".xtream-only").forEach((node) => node.classList.toggle("hidden", !isXtream));
  document.querySelectorAll(".m3u-only").forEach((node) => node.classList.toggle("hidden", isXtream));
}

function populateProviderForm(provider = null) {
  const item = provider || { id: "", name: "", type: "xtream", xtreamServerUrl: "", xtreamUsername: "", xtreamPassword: "", m3uPlaylistUrl: "", cacheTtlSeconds: 300, isActive: 0 };
  el.providerIdInput.value = item.id || "";
  el.providerNameInput.value = item.name || "";
  el.providerTypeSelect.value = item.type || "xtream";
  el.xtreamServerUrlInput.value = item.xtreamServerUrl || "";
  el.xtreamUsernameInput.value = item.xtreamUsername || "";
  el.xtreamPasswordInput.value = item.xtreamPassword || "";
  el.m3uPlaylistUrlInput.value = item.m3uPlaylistUrl || "";
  el.cacheTtlInput.value = item.cacheTtlSeconds || 300;
  el.providerActiveCheckbox.checked = Boolean(item.isActive);
  el.deleteProviderButton.disabled = !item.id;
  updateProviderTypeVisibility();
}

function renderProviders() {
  el.providerList.innerHTML = "";
  if (!state.providers.length) {
    el.providerList.innerHTML = '<div class="empty-state">No providers saved yet.</div>';
    return;
  }
  for (const provider of state.providers) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "provider-row";
    if (provider.id === state.selectedProviderId) row.classList.add("selected");
    if (provider.id === state.activeProvider?.id) row.classList.add("active");
    row.innerHTML = `<div class="provider-topline"><div><strong>${html(provider.name)}</strong><div class="subtle">${provider.type === "xtream" ? "Xtream Codes" : "M3U Playlist"}</div></div>${provider.id === state.activeProvider?.id ? '<span class="pill active">Active</span>' : '<span class="pill">Stored</span>'}</div>`;
    row.addEventListener("click", () => {
      state.selectedProviderId = provider.id;
      populateProviderForm(provider);
      renderProviders();
    });
    row.addEventListener("dblclick", async () => {
      try {
        const result = await window.desktopApi.activateProvider(provider.id);
        state.providers = result.providers || state.providers;
        state.activeProvider = result.activeProvider || null;
        state.selectedProviderId = provider.id;
        populateProviderForm(state.providers.find((item) => item.id === provider.id) || provider);
        renderProviders();
        hydrateSettings();
        await refreshStreams();
        showToast("Provider activated.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
    el.providerList.appendChild(row);
  }
}

function renderApiEndpointState() {
  const backendApi = endpointConfig("backend");
  const publicApi = endpointConfig("public");
  const applyEndpointUi = (kind, config) => {
    const urlInput = kind === "public" ? el.publicApiUrlInput : el.backendApiUrlInput;
    const tokenInput = kind === "public" ? el.publicApiTokenInput : el.backendApiTokenInput;
    const connectButton = kind === "public" ? el.publicApiConnectButton : el.backendApiConnectButton;
    const disconnectButton = kind === "public" ? el.publicApiDisconnectButton : el.backendApiDisconnectButton;
    const testButton = kind === "public" ? el.publicApiTestButton : el.backendApiTestButton;
    const editable = !config.connected;
    const hasValidDraft = isValidHttpUrl(config.url) && String(config.apiToken || "").trim().length > 0;
    if (urlInput) {
      urlInput.readOnly = !editable;
      urlInput.disabled = !editable;
    }
    if (tokenInput) {
      tokenInput.readOnly = !editable;
      tokenInput.disabled = !editable;
    }
    if (connectButton) {
      connectButton.disabled = !editable || !hasValidDraft;
    }
    if (disconnectButton) {
      disconnectButton.disabled = editable;
    }
    if (testButton) {
      testButton.disabled = !hasValidDraft;
    }
  };
  if (el.backendApiState) {
    el.backendApiState.textContent = backendApi.connected ? "Connected" : "Disconnected";
    el.backendApiState.className = `pill ${backendApi.connected ? "active" : ""}`;
  }
  if (el.publicApiState) {
    el.publicApiState.textContent = publicApi.connected ? "Connected" : "Disconnected";
    el.publicApiState.className = `pill ${publicApi.connected ? "active" : ""}`;
  }
  applyEndpointUi("backend", backendApi);
  applyEndpointUi("public", publicApi);
}

function hydrateSettings() {
  const backendApi = endpointConfig("backend");
  const publicApi = endpointConfig("public");
  if (el.backendApiUrlInput) el.backendApiUrlInput.value = backendApi.url || DEFAULT_API_URL;
  if (el.backendApiTokenInput) el.backendApiTokenInput.value = backendApi.apiToken || "";
  if (el.publicApiUrlInput) el.publicApiUrlInput.value = publicApi.url || DEFAULT_API_URL;
  if (el.publicApiTokenInput) el.publicApiTokenInput.value = publicApi.apiToken || "";
  if (el.chromePreviewApiToggle) {
    el.chromePreviewApiToggle.checked = false;
    el.chromePreviewApiToggle.disabled = true;
    el.chromePreviewApiToggle.title = "Chrome preview always uses Backend API.";
  }
  el.adminUsernameInput.value = state.settings.adminUsername || "";
  el.adminPasswordInput.value = state.settings.adminPassword || "";
  el.tenantUsernameInput.value = state.settings.tenantUsername || "";
  el.tenantPasswordInput.value = state.settings.tenantPassword || "";
  el.settingsBackendUrlMirror.value = backendApi.url || "";
  el.settingsTenantMirror.value = state.session.adminEmail || effectiveTenantId();
  el.settingsTenantUserMirror.value = state.session.deviceId || "-";
  el.welcomeClientLabel.textContent = `Welcome, ${state.session.adminName || state.branding?.name || "Client"}`;
  el.headerSubscriptionLabel.textContent = `Subscription: ${state.session.subscriptionStatus || "-"}`;
  el.headerPlanLabel.textContent = `Plan: ${state.session.planId || state.session.plan_id || "-"}`;
  el.headerServerLabel.textContent = `Server ID: ${state.session.serverId || "-"}`;
  el.tenantSelect.innerHTML = optionMarkup((state.tenants || []).map((item) => ({ id: item.tenant_id, name: item.name })), effectiveTenantId()) || '<option value="default">default</option>';

  const branding = state.branding?.branding || {};
  applyDashboardBranding(branding);
  el.brandingAppNameInput.value = branding.app_name || "";
  el.brandingPrimaryColorInput.value = branding.primary_color || "";
  el.brandingAccentColorInput.value = branding.accent_color || branding.secondary_color || "";
  el.brandingSecondaryColorInput.value = branding.secondary_color || branding.accent_color || "";
  el.brandingSurfaceColorInput.value = branding.surface_color || "";
  el.brandingBackgroundColorInput.value = branding.background_color || "";
  el.brandingTextColorInput.value = branding.text_color || "";
  if (el.mobileBuilderAppNameInput) el.mobileBuilderAppNameInput.value = branding.app_name || "";
  if (el.mobileBuilderPackageInput) el.mobileBuilderPackageInput.value = branding.package_name || "";
  if (el.mobileBuilderServerUrlInput) el.mobileBuilderServerUrlInput.value = branding.server_url || branding.api_base_url || publicApi.url || DEFAULT_API_URL;
  if (el.mobileBuilderPrimaryColorInput) el.mobileBuilderPrimaryColorInput.value = branding.primary_color || "";
  if (el.mobileBuilderSecondaryColorInput) el.mobileBuilderSecondaryColorInput.value = branding.secondary_color || branding.accent_color || "";
  if (el.mobileBuilderTenantIdLabel) el.mobileBuilderTenantIdLabel.value = effectiveTenantId();
  applyMobileBuildLockState();
  renderApiEndpointState();

  const backup = state.backup.configured || state.settings;
  el.backupPathInput.value = backup.backupPath || "";
  el.backupScheduleSelect.value = backup.backupSchedule || "disabled";
  el.backupRetentionInput.value = backup.backupRetention || "7";
  el.cloudBackupEnabledInput.value = backup.cloudBackupEnabled || "0";
  el.s3BucketInput.value = backup.s3Bucket || "";
  el.s3PrefixInput.value = backup.s3Prefix || "football-iptv-backups";
  el.awsRegionInput.value = backup.awsRegion || "";

  const python = state.backup.python || {};
  const runtimeText = python.available ? (python.executable || "Bundled runtime ready") : "Bundled Python missing";
  const lastBackup = state.backup.recent_logs?.length ? state.backup.recent_logs[state.backup.recent_logs.length - 1] : null;
  const lastBackupText = lastBackup ? `${lastBackup.success ? "Success" : "Failed"} - ${formatDate(lastBackup.finished_at || lastBackup.started_at)}` : "No backup run yet.";
  el.pythonRuntimeLabel.textContent = runtimeText;
  el.backupRuntimeMirror.textContent = runtimeText;
  el.backupLastRunLabel.textContent = lastBackupText;
  el.backupLastRunMirror.textContent = lastBackupText;
  el.backupCountLabel.textContent = `${(state.backup.backups || []).length} archives`;
  el.activeProviderLabel.textContent = state.activeProvider?.name || "None";

  metric(el.totalUsersLabel, state.userStats.total_users);
  metric(el.trialUsersLabel, state.userStats.trial_users);
  metric(el.activeUsersLabel, state.userStats.active_users);
  metric(el.blockedUsersLabel, state.userStats.blocked_users);
  metric(el.liveViewersLabel, state.userStats.live_viewers);
  metric(el.nationCountLabel, state.nations.length);
  metric(el.competitionCountLabel, state.competitions.length);
  metric(el.approvedCountLabel, state.approvedMatches.length);
  el.userCountCaption.textContent = `${state.users.length} users`;
  el.onlineCountCaption.textContent = `${state.onlineUsers.length} live`;
  if (el.providerWorkspaceList) {
    el.providerWorkspaceList.innerHTML = state.providers.length
      ? state.providers.map((provider) => `<article class="analytics-row"><div><strong>${html(provider.name)}</strong><div class="subtle">${html(provider.type === "xtream" ? "Xtream Codes" : "M3U Playlist")}</div></div>${provider.id === state.activeProvider?.id ? '<span class="pill active">Active</span>' : '<span class="pill">Stored</span>'}</article>`).join("")
      : '<div class="empty-state">No providers saved yet.</div>';
  }
}

function applyDashboardBranding(branding) {
  const appName = branding.app_name || state.branding?.name || "IPTV Desk";
  document.title = appName;
  document.documentElement.style.setProperty("--tenant-primary", branding.primary_color || "#11B37C");
  document.documentElement.style.setProperty("--tenant-secondary", branding.secondary_color || branding.accent_color || "#7EE3AF");
  const faviconUrl = state.branding?.tenant_branding?.favicon_path || branding.favicon_path || "";
  if (!faviconUrl) return;
  let link = document.querySelector("link[rel='icon']");
  if (!link) {
    link = document.createElement("link");
    link.setAttribute("rel", "icon");
    document.head.appendChild(link);
  }
  link.setAttribute("href", faviconUrl);
}

function applyMobileBuildLockState() {
  const generated = mobileAppAlreadyGenerated();
  const packageId = state.branding?.mobile_app_package_id || state.mobileBuilder.status?.mobile_app_package_id || "";
  const createdAt = state.branding?.mobile_app_created_at || state.mobileBuilder.status?.mobile_app_created_at || "";
  const buildStatus = String(state.mobileBuilder.status?.status || "").toLowerCase();
  const canCancel = ["queued", "building", "cancelling"].includes(buildStatus) && Boolean(state.mobileBuilder.activeBuildId);
  if (el.generateMobileApkButton) {
    el.generateMobileApkButton.disabled = generated || canCancel;
  }
  if (el.cancelMobileBuildButton) {
    el.cancelMobileBuildButton.disabled = !canCancel;
  }
  if (el.mobileBuildLockMessage) {
    el.mobileBuildLockMessage.textContent = canCancel
      ? "A mobile build is in progress. You can cancel it and start again after the worker stops."
      : generated
      ? `Mobile application already created${packageId ? ` (${packageId})` : ""}. You can modify branding but cannot generate a new app.${createdAt ? ` First generated ${formatDate(createdAt)}.` : ""}`
      : "Branding updates sync into the installed mobile app on launch and every 12 hours.";
  }
}

function renderUsers() {
  if (!el.userList) return;
  el.userList.innerHTML = "";
  if (!state.users.length) {
    el.userList.innerHTML = '<tr><td colspan="4" class="empty-table">Devices will appear here automatically after the mobile app registers.</td></tr>';
    return;
  }
  for (const user of state.users) {
    const row = document.createElement("tr");
    row.innerHTML = `<td><div><strong>${html(user.username || user.display_name || user.device_name || user.device_id || "-")}</strong><div class="subtle">${html(user.device_id || "-")}</div></div></td><td>${statusPill(user.status)}</td><td>${html(formatDate(user.expiry_date || user.subscription_end || user.trial_end))}</td><td><div class="table-actions"><button class="primary-button small-button extend">Extend</button><button class="ghost-button small-button block">Block</button><button class="ghost-button small-button unblock">Unblock</button></div></td>`;
    row.querySelector(".block").addEventListener("click", () => runUserAction(() => window.desktopApi.blockUser({ device_id: user.device_id }), "User blocked."));
    row.querySelector(".unblock").addEventListener("click", () => runUserAction(() => window.desktopApi.unblockUser({ device_id: user.device_id }), "User unblocked."));
    row.querySelector(".extend").addEventListener("click", () => extendUser(user));
    el.userList.appendChild(row);
  }
}

function renderOnlineUsers() {
  el.onlineUserList.innerHTML = "";
  if (!state.onlineUsers.length) {
    el.onlineUserList.innerHTML = '<div class="empty-state">No recently active devices.</div>';
    return;
  }
  for (const user of state.onlineUsers) {
    const card = document.createElement("article");
    card.className = "online-card";
    card.innerHTML = `<strong>${html(user.display_name || user.device_name)}</strong><div class="subtle">${html(user.device_id || "-")}</div><div class="subtle">${html(user.last_ip || "-")} ${html(user.last_country || "")}</div><div class="subtle">Last seen: ${html(formatDate(user.last_seen))}</div>`;
    el.onlineUserList.appendChild(card);
  }
}

function renderEntityList(node, items, emptyMessage, onClick, onDoubleClick) {
  node.innerHTML = "";
  if (!items.length) {
    node.innerHTML = `<div class="empty-state">${emptyMessage}</div>`;
    return;
  }
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "list-item";
    if (item.id === state.selectedNationId && item.typeHint === "nation") button.classList.add("active");
    if (item.id === state.selectedCompetitionId && item.typeHint === "competition") button.classList.add("active");
    button.innerHTML = item.markup;
    if (onClick) button.addEventListener("click", () => onClick(item));
    if (onDoubleClick) button.addEventListener("dblclick", () => onDoubleClick(item));
    button.querySelectorAll("[data-action]").forEach((actionButton) => {
      actionButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const action = actionButton.dataset.action;
        const id = actionButton.dataset.id;
        const type = actionButton.dataset.type;
        if (action === "edit") editItem(id, type);
        if (action === "delete") deleteItem(id, type);
      });
    });
    node.appendChild(button);
  }
}

function renderMetadataLists() {
  const actionButtons = (item, type) => `<div class="list-item-actions"><button type="button" class="ghost-button small-button" data-action="edit" data-id="${html(item.id)}" data-type="${html(type)}">Edit</button><button type="button" class="ghost-button small-button" data-action="delete" data-id="${html(item.id)}" data-type="${html(type)}">Delete</button></div>`;
  const itemContent = (item, label, subtitle) => `
    <div class="row-with-logo">
      ${logoMarkup(item.logo_url, label)}
      <div>
        <strong>${html(label)}</strong>
        <span class="subtle">${html(subtitle)}</span>
      </div>
    </div>
  `;
  const nations = state.nations.map((nation) => ({
    ...nation,
    typeHint: "nation",
    markup: `${itemContent(nation, nation.name, `${state.competitions.filter((item) => item.nation_id === nation.id).length} competitions`)}${actionButtons(nation, "nation")}`,
  }));
  const visibleCompetitions = state.selectedNationId ? state.competitions.filter((item) => item.nation_id === state.selectedNationId) : state.competitions;
  const competitions = visibleCompetitions.map((competition) => ({
    ...competition,
    typeHint: "competition",
    markup: `${itemContent(competition, competition.name, `${competition.participant_type || "clubs"} / ${(getCompetitionClubLink(competition.id)?.club_ids || []).length} linked clubs`)}${actionButtons(competition, "competition")}`,
  }));
  const visibleClubs = getVisibleClubsForCompetition(state.selectedCompetitionId);
  const clubs = visibleClubs.map((club) => ({
    ...club,
    typeHint: "club",
    markup: `${itemContent(club, club.name, (club.competition_ids || []).length ? `${(club.competition_ids || []).length} linked competitions` : "Reusable club")}${actionButtons(club, "club")}`,
  }));

  const selectNation = (nation) => {
    state.selectedNationId = nation.id;
    state.selectedCompetitionId = null;
    renderMetadataLists();
  };
  const selectCompetition = (competition) => {
    state.selectedNationId = competition.nation_id || state.selectedNationId;
    state.selectedCompetitionId = competition.id;
    renderMetadataLists();
  };
  const editNation = (nation) => openEntityModal("nation", nation);
  const editCompetition = (competition) => openEntityModal("competition", competition);
  const editClub = (club) => openEntityModal("club", club);

  [el.nationList, el.catalogNationList].forEach((node) => renderEntityList(node, nations, "Create a nation to start.", selectNation, editNation));
  [el.competitionList, el.catalogCompetitionList].forEach((node) => renderEntityList(node, competitions.map((competition) => ({
    ...competition,
    markup: competition.markup,
  })), "No competitions yet.", selectCompetition, editCompetition));
  const clubEmptyMessage = selectedCompetition ? "No clubs linked to this competition." : "Select a competition to view linked clubs.";
  [el.clubList, el.catalogClubList].forEach((node) => renderEntityList(node, clubs, clubEmptyMessage, null, editClub));
}

async function editItem(id, type) {
  const collection = type === "nation" ? state.nations : type === "competition" ? state.competitions : state.clubs;
  const item = collection.find((entry) => String(entry.id) === String(id));
  if (!item) {
    showToast("Catalog item not found.", true);
    return;
  }
  openEntityModal(type, item);
}

async function deleteItem(id, type) {
  try {
    if (type === "nation") await window.desktopApi.deleteNation(id);
    if (type === "competition") await window.desktopApi.deleteCompetition(id);
    if (type === "club") await window.desktopApi.deleteClub(id);
    removeCatalogStateItem(type, id);
    await refreshMetadata();
    showToast("Catalog item deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderGroups() {
  if (el.streamProviderSelect) {
    const providers = state.activeProviders || [];
    el.streamProviderSelect.innerHTML = providers.length
      ? providers.map((item) => `<option value="${html(item.id)}" ${String(item.id) === String(state.selectedStreamProviderId || "") ? "selected" : ""}>${html(item.name || `Provider ${item.id}`)}</option>`).join("")
      : '<option value="">No active provider</option>';
    el.streamProviderSelect.disabled = !providers.length;
  }
  el.groupList.innerHTML = "";
  el.groupSummary.textContent = `${state.groups.length} groups`;
  if (!(state.activeProviders || []).length) {
    el.groupList.innerHTML = '<div class="empty-state">No active provider available for this account.</div>';
    return;
  }
  if (!state.groups.length) {
    el.groupList.innerHTML = '<div class="empty-state">No groups found for the selected active provider.</div>';
    return;
  }
  for (const group of state.groups) {
    const count = Array.isArray(group.channels) ? group.channels.length : 0;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "list-item";
    if (group.id === state.selectedGroup) button.classList.add("active");
    button.innerHTML = `<strong>${html(group.name)}</strong><span class="subtle">${count} channels</span>`;
    button.addEventListener("click", () => {
      state.selectedGroup = group.id;
      state.selectedChannel = null;
      renderGroups();
      renderChannels();
      renderApprovalPanel();
      renderPreview();
    });
    el.groupList.appendChild(button);
  }
}
function getCompetitionOptions() {
  return state.competitions.filter((item) => item.nation_id === (el.approveNationSelect.value || state.nations[0]?.id || ""));
}

function getClubOptions() {
  const competitionId = el.approveCompetitionSelect.value || "";
  if (!competitionId) return [];
  return state.clubs.filter((item) => (item.competition_ids || []).includes(competitionId));
}

function selectChannel(channel) {
  state.selectedChannel = channel;
  renderChannels();
  renderApprovalPanel();
  renderPreview();
}

function renderChannels() {
  el.channelList.innerHTML = "";
  if (!(state.activeProviders || []).length) {
    el.channelPaneSubtitle.textContent = "No active provider available.";
    el.channelList.innerHTML = '<div class="empty-state">Activate a provider to load source streams.</div>';
    return;
  }
  if (!state.selectedGroup) {
    el.channelPaneSubtitle.textContent = "Select a group to browse source streams.";
    el.channelList.innerHTML = '<div class="empty-state">Choose a provider group.</div>';
    return;
  }
  const selectedGroup = state.groups.find((group) => String(group.id) === String(state.selectedGroup)) || null;
  const filtered = selectedGroup?.channels?.length
    ? selectedGroup.channels.map((channel) => ({
        ...channel,
        group: selectedGroup.name,
      }))
    : state.streams.filter((stream) => (stream.group || "Ungrouped").toLowerCase().replace(/\s+/g, "-") === state.selectedGroup);
  el.channelPaneSubtitle.textContent = `${filtered.length} source streams in ${selectedGroup?.name || state.selectedGroup}`;
  const mapped = approvedMap();
  for (const channel of filtered) {
    const approval = mapped.get(String(channel.id || channel.stream_id));
    const card = document.createElement("article");
    card.className = "channel-card";
    if (String(state.selectedChannel?.id || state.selectedChannel?.stream_id) === String(channel.id || channel.stream_id)) card.classList.add("active");
    card.innerHTML = `<div class="approved-topline"><div><strong>${html(channel.name || channel.raw_name || "Unnamed stream")}</strong><div class="subtle">ID: ${html(channel.id || channel.stream_id || "-")}</div></div>${approval ? `<span class="pill active">${html(approval.home_club_name)} vs ${html(approval.away_club_name)}</span>` : '<span class="pill">Unmapped</span>'}</div><div class="form-actions"><button class="ghost-button small-button preview-button">Preview</button><button class="primary-button small-button map-button">${approval ? "Edit Mapping" : "Map Match"}</button></div>`;
    card.addEventListener("click", () => {
      selectChannel(channel);
      playStream(channel);
    });
    card.querySelector(".preview-button").addEventListener("click", (event) => {
      event.stopPropagation();
      selectChannel(channel);
      playStream(channel);
    });
    card.querySelector(".map-button").addEventListener("click", (event) => {
      event.stopPropagation();
      selectChannel(channel);
      playStream(channel);
      setActiveSection("streams");
    });
    el.channelList.appendChild(card);
  }
  if (!filtered.length) el.channelList.innerHTML = '<div class="empty-state">No channels available.</div>';
}

function playStream(channel) {
  const video = el.videoPreview;
  const url = channel?.stream_url || channel?.url || "";
  if (!url) {
    console.error("Missing stream URL", channel);
    el.previewOverlay.textContent = "This stream is missing a playback URL.";
    el.previewOverlay.classList.remove("hidden");
    return;
  }
  console.log("Playing stream:", url);
  el.previewOverlay.textContent = "Loading stream preview...";
  setVideoSource(url);
  const playPromise = video.play();
  if (playPromise && typeof playPromise.catch === "function") {
    playPromise.catch((error) => console.warn("Preview autoplay failed", error));
  }
}

function updateApprovalPreview() {
  const competition = state.competitions.find((item) => item.id === el.approveCompetitionSelect.value);
  const homeClub = state.clubs.find((item) => item.id === el.approveHomeClubSelect.value);
  const awayClub = state.clubs.find((item) => item.id === el.approveAwayClubSelect.value);
  el.approveCompetitionNamePreview.textContent = competition?.name || "-";
  el.approveHomeClubNamePreview.textContent = homeClub?.name || "Home";
  el.approveAwayClubNamePreview.textContent = awayClub?.name || "Away";
  el.approvePreviewLabel.textContent = competition && homeClub && awayClub ? `${competition.name}: ${homeClub.name} vs ${awayClub.name}` : "Select the football metadata for this stream.";
  paintLogo(el.approveCompetitionLogoPreview, competition?.logo_url || "", competition?.name || "competition");
  paintLogo(el.approveHomeClubLogoPreview, homeClub?.logo_url || "", homeClub?.name || "home");
  paintLogo(el.approveAwayClubLogoPreview, awayClub?.logo_url || "", awayClub?.name || "away");
}

function syncApproveSelections(existingMatch = null) {
  const competitions = getCompetitionOptions();
  el.approveCompetitionSelect.innerHTML = optionMarkup(competitions, existingMatch?.competition_id || competitions[0]?.id || "");
  const clubs = getClubOptions();
  el.approveHomeClubSelect.innerHTML = optionMarkup(clubs, existingMatch?.home_club_id || clubs[0]?.id || "");
  el.approveAwayClubSelect.innerHTML = optionMarkup(clubs, existingMatch?.away_club_id || clubs[1]?.id || clubs[0]?.id || "");
  updateApprovalPreview();
}

function renderApprovalPanel() {
  const channel = state.selectedChannel;
  const approval = channel ? approvedMap().get(String(channel.id || channel.stream_id)) : null;
  el.approvalSelectedStream.textContent = channel ? (channel.name || channel.raw_name || channel.match_label || "Selected stream") : "No stream selected";
  el.approveNationSelect.disabled = !channel;
  el.approveCompetitionSelect.disabled = !channel;
  el.approveHomeClubSelect.disabled = !channel;
  el.approveAwayClubSelect.disabled = !channel;
  el.approveKickoffInput.disabled = !channel;
  if (!state.nations.length) {
    el.approveNationSelect.innerHTML = "";
    el.approveCompetitionSelect.innerHTML = "";
    el.approveHomeClubSelect.innerHTML = "";
    el.approveAwayClubSelect.innerHTML = "";
    updateApprovalPreview();
    return;
  }
  el.approveNationSelect.innerHTML = optionMarkup(state.nations, approval?.nation_id || state.selectedNationId || state.nations[0]?.id || "");
  syncApproveSelections(approval || null);
  el.approveKickoffInput.value = approval?.kickoff_label || "";
}

function setVideoSource(url) {
  const video = el.videoPreview;
  if (hls) {
    hls.destroy();
    hls = null;
  }
  video.pause();
  video.removeAttribute("src");
  video.load();
  if (!url) {
    el.previewOverlay.textContent = "No stream selected";
    el.previewOverlay.classList.remove("hidden");
    return;
  }
  el.previewOverlay.classList.add("hidden");
  const normalizedUrl = String(url || "").trim().toLowerCase();
  const isHlsStream = normalizedUrl.includes(".m3u8") || normalizedUrl.includes("format=m3u8");
  if (isHlsStream && window.Hls && window.Hls.isSupported()) {
    hls = new window.Hls({ enableWorker: true });
    hls.on(window.Hls.Events.ERROR, (_event, data) => {
      if (!data?.fatal) {
        return;
      }
      console.error("HLS preview error", data);
      el.previewOverlay.textContent = "The stream could not be loaded in preview.";
      el.previewOverlay.classList.remove("hidden");
      if (hls) {
        hls.destroy();
        hls = null;
      }
    });
    hls.loadSource(url);
    hls.attachMedia(video);
    return;
  }
  video.src = url;
}

function renderPreview() {
  const channel = state.selectedChannel;
  const approval = channel ? approvedMap().get(String(channel.id || channel.stream_id)) : null;
  el.previewTitle.textContent = channel ? (approval?.match_label || channel.name || channel.raw_name || "Selected stream") : "Choose a stream to preview and approve.";
  el.previewGroup.textContent = channel ? (channel.group || channel.competition_name || "Approved Match") : "-";
  el.previewId.textContent = channel ? (channel.name || channel.raw_name || channel.stream_id || "-") : "-";
  el.previewCompetition.textContent = approval ? `${approval.competition_name} / ${approval.home_club_name} vs ${approval.away_club_name}` : "Not mapped";
  el.approveChannelButton.disabled = !channel;
  el.removeApprovedButton.disabled = !approval;
  if (!channel) setVideoSource("");
}

function renderApprovedMatches() {
  el.approvedList.innerHTML = "";
  if (!state.approvedMatches.length) {
    el.approvedList.innerHTML = '<div class="empty-state">Approved football matches will appear here.</div>';
    return;
  }
  for (const match of state.approvedMatches) {
    const row = document.createElement("article");
    row.className = "approved-row";
    row.innerHTML = `<div class="approved-topline"><div class="row-with-logo">${approvedMatchLogoMarkup(match)}<div><strong>${html(match.home_club_name)} vs ${html(match.away_club_name)}</strong><div class="subtle">${html(match.nation_name)} / ${html(match.competition_name)}</div></div></div><span class="pill active">${html(match.kickoff_label || "Live")}</span></div><div class="form-actions"><button class="ghost-button small-button preview-match">Preview</button><button class="ghost-button small-button remove-match">Remove</button></div>`;
    row.querySelector(".preview-match").addEventListener("click", () => {
      selectChannel(match);
      playStream(match);
    });
    row.querySelector(".remove-match").addEventListener("click", async () => {
      try {
        await window.desktopApi.removeApprovedStream(match.stream_id);
        await refreshApprovedMatches();
        renderChannels();
        showToast("Match mapping removed.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
    el.approvedList.appendChild(row);
  }
}

function renderAnalyticsRows(nodes, items, emptyMessage, mapper) {
  [].concat(nodes).filter(Boolean).forEach((node) => {
    node.innerHTML = "";
    if (!items.length) {
      node.innerHTML = `<div class="empty-state">${emptyMessage}</div>`;
      return;
    }
    for (const item of items) {
      const row = document.createElement("article");
      row.className = "analytics-row";
      row.innerHTML = mapper(item);
      node.appendChild(row);
    }
  });
}

function renderAnalytics() {
  const live = state.analytics.live || { live_viewers: 0, streams: [], competitions: [] };
  metric(el.analyticsLiveViewersLabels, live.live_viewers || 0);
  metric(el.analyticsActiveStreamsLabels, (live.streams || []).length);
  metric(el.analyticsCompetitionsLabels, (live.competitions || []).length);
  el.analyticsRefreshLabel.textContent = `Updated ${new Date().toLocaleTimeString()} | Auto refresh: 10s`;

  renderAnalyticsRows(el.analyticsStreamsLists, state.analytics.streams, "No active streams right now.", (item) => `<div><strong>${html(item.match || item.stream_id)}</strong><div class="subtle">${html(item.competition || "-")}</div></div><div class="analytics-value">${html(item.current_viewers || item.viewers || 0)}</div>`);
  renderAnalyticsRows(el.analyticsTopMatchesList, state.analytics.topMatches, "No completed viewer sessions yet.", (item) => `<div><strong>${html(item.match || "-")}</strong><div class="subtle">${html(item.competition || "-")} | ${html(item.unique_devices || 0)} devices</div></div><div class="analytics-value">${html(item.viewers || 0)}</div>`);
  renderAnalyticsRows(el.analyticsTopCompetitionsList, state.analytics.topCompetitions, "No competition analytics yet.", (item) => `<div><strong>${html(item.competition || "-")}</strong><div class="subtle">Watch time ${html(item.watch_time || 0)}s</div></div><div class="analytics-value">${html(item.viewers || 0)}</div>`);
  renderAnalyticsRows(el.analyticsCountriesList, state.analytics.countries, "Country data not available yet.", (item) => `<div><strong>${html(item.country || "-")}</strong></div><div class="analytics-value">${html(item.viewers || 0)}</div>`);
  renderAnalyticsCharts();
}

function renderMasterLive() {
  if (!el.masterLiveList) return;
  const payload = state.masterLive || {};
  const version = payload.version || {};
  const streamItems = payload.streams?.items || [];
  const liveMatches = payload.liveScores?.matches || [];
  const standingGroups = payload.standings?.standings || [];
  const standingTable = standingGroups.find((item) => Array.isArray(item.table))?.table || [];
  const fixtures = payload.fixtures?.matches || [];

  el.masterLiveVersionLabel.textContent = version.desktop?.latest_version || version.desktop?.version || "-";
  el.masterLiveStreamsLabel.textContent = String(streamItems.length || 0);
  el.masterLiveScoresLabel.textContent = String(liveMatches.length || 0);
  el.masterLiveUpdatedLabel.textContent = payload.lastUpdatedAt ? `Updated ${formatDate(payload.lastUpdatedAt)}` : "Waiting for refresh...";

  const rows = [];
  if (payload.error) {
    rows.push(`<article class="analytics-row"><div><strong>Refresh Error</strong><div class="subtle">${html(payload.error)}</div></div><div class="analytics-value">error</div></article>`);
  }
  for (const item of liveMatches.slice(0, 3)) {
    rows.push(`<article class="analytics-row"><div><strong>${html(`${item.homeTeam?.shortName || item.homeTeam?.name || "Home"} vs ${item.awayTeam?.shortName || item.awayTeam?.name || "Away"}`)}</strong><div class="subtle">${html(item.status || "LIVE")}</div></div><div class="analytics-value">${html(`${item.score?.fullTime?.home ?? "-"}:${item.score?.fullTime?.away ?? "-"}`)}</div></article>`);
  }
  for (const item of fixtures.slice(0, 2)) {
    rows.push(`<article class="analytics-row"><div><strong>${html(`${item.homeTeam?.shortName || item.homeTeam?.name || "Home"} vs ${item.awayTeam?.shortName || item.awayTeam?.name || "Away"}`)}</strong><div class="subtle">${html(formatDate(item.utcDate || ""))}</div></div><div class="analytics-value">${html(item.status || "SCHEDULED")}</div></article>`);
  }
  for (const item of standingTable.slice(0, 3)) {
    rows.push(`<article class="analytics-row"><div><strong>${html(`${item.position || "-"} . ${item.team?.shortName || item.team?.name || "Team"}`)}</strong><div class="subtle">${html(`${item.playedGames || 0} played`)}</div></div><div class="analytics-value">${html(item.points || 0)}</div></article>`);
  }
  if (!rows.length) {
    rows.push('<div class="empty-state">Master live feed will appear here after authentication.</div>');
  }
  el.masterLiveList.innerHTML = rows.join("");
}

function renderAnalyticsCharts() {
  if (!window.Chart) return;
  const dailyLabels = state.analytics.dailyViewers.map((item) => item.date || "");
  const dailyValues = state.analytics.dailyViewers.map((item) => Number(item.viewer_sessions || 0));
  const competitionLabels = state.analytics.topCompetitions.map((item) => item.competition || "");
  const competitionValues = state.analytics.topCompetitions.map((item) => Number(item.viewers || 0));
  if (dailyViewersChart) dailyViewersChart.destroy();
  if (competitionPopularityChart) competitionPopularityChart.destroy();
  dailyViewersChart = new window.Chart(el.dailyViewersChart, { type: "line", data: { labels: dailyLabels, datasets: [{ label: "Viewer Sessions", data: dailyValues, borderColor: "#39d98a", backgroundColor: "rgba(57, 217, 138, 0.18)", fill: true, tension: 0.35 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#edf4ff" } } }, scales: { x: { ticks: { color: "#8fa6c4" }, grid: { color: "rgba(255,255,255,0.06)" } }, y: { ticks: { color: "#8fa6c4" }, grid: { color: "rgba(255,255,255,0.06)" } } } } });
  competitionPopularityChart = new window.Chart(el.competitionPopularityChart, { type: "bar", data: { labels: competitionLabels, datasets: [{ label: "Viewers", data: competitionValues, backgroundColor: ["#1fc9b1", "#39d98a", "#f3bc68", "#60a5fa", "#fb7185", "#f59e0b"] }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#edf4ff" } } }, scales: { x: { ticks: { color: "#8fa6c4" }, grid: { color: "rgba(255,255,255,0.03)" } }, y: { ticks: { color: "#8fa6c4" }, grid: { color: "rgba(255,255,255,0.06)" } } } } });
}
function renderSecurity() {
  const security = state.security || {};
  el.securityFlaggedCount.textContent = `${(security.flagged_devices || []).length} flagged`;
  el.securityVpnCount.textContent = `${(security.vpn_users || []).length} vpn`;
  el.securityBlockedCount.textContent = `${(security.blocked_devices || []).length} blocked`;
  renderAnalyticsRows(el.securityFlaggedLists, security.flagged_devices || [], "No flagged devices.", (item) => `<div><strong>${html(item.display_name || item.device_name || item.device_id)}</strong><div class="subtle">${html(item.device_id || "-")}</div></div><div class="analytics-value">${html(item.status || "-")}</div>`);
  renderAnalyticsRows(el.securityVpnList, security.vpn_users || [], "No VPN users detected.", (item) => `<div><strong>${html(item.display_name || item.device_name || item.device_id)}</strong><div class="subtle">${html(item.last_ip || "-")} | ${html(item.last_country || "-")}</div></div><div class="analytics-value">${html(item.vpn_policy || "allow")}</div>`);
  renderAnalyticsRows(el.securityBlockedList, security.blocked_devices || [], "No blocked devices.", (item) => `<div><strong>${html(item.display_name || item.device_name || item.device_id)}</strong><div class="subtle">${html(item.device_id || "-")}</div></div><div class="analytics-value">${html(item.status || "-")}</div>`);
  renderAnalyticsRows(el.securityIpList, security.suspicious_ip_changes || [], "No suspicious IP changes.", (item) => `<div><strong>${html(item.display_name || item.device_name || item.device_id)}</strong><div class="subtle">${html(item.last_ip || "-")} | ${html(item.last_country || "-")}</div></div><div class="analytics-value">${html((item.ip_history || []).length || 0)}</div>`);
  renderAnalyticsRows(el.securityLogsList, security.security_logs || [], "No security log entries.", (item) => `<div><strong>${html(item.issue || "-")}</strong><div class="subtle">${html(item.device_id || "-")} | ${html(formatDate(item.timestamp))}</div><div class="subtle">${html(item.detail || "")}</div></div><div class="analytics-value">log</div>`);
}

function renderBackups() {
  renderAnalyticsRows(el.backupList, state.backup.backups || [], "No backup archives yet.", (item) => `<div><strong>${html(item.name || "backup.zip")}</strong><div class="subtle">${html(formatDate(item.modified_at))}</div><div class="subtle">${html(item.path || "")}</div></div><div class="form-actions"><button class="ghost-button small-button restore-backup" data-path="${html(item.path || "")}">Restore</button></div>`);
  el.backupList.querySelectorAll(".restore-backup").forEach((button) => {
    button.addEventListener("click", async () => {
      const archivePath = button.dataset.path || "";
      if (!archivePath) return;
      if (!window.confirm(`Restore backup?\n\n${archivePath}\n\nThis replaces backend data files.`)) return;
      try {
        await window.desktopApi.restoreBackup(archivePath);
        await refreshBackups();
        showToast("Backup restored.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  renderAnalyticsRows(el.backupLogLists, state.backup.task_logs || [], "No backup task logs yet.", (item) => `<div><strong>${html(item.type || "backup")}</strong><div class="subtle">${html(formatDate(item.finished_at || item.started_at))}</div><div class="subtle">${html(item.archive_path || item.error || "")}</div></div><div class="analytics-value">${html(item.success ? "ok" : "error")}</div>`);
}

function renderPlatformClients() {
  if (el.platformClientsTotalLabel) {
    el.platformClientsTotalLabel.textContent = String(state.platformClients.stats.total_clients || 0);
    el.platformClientsActiveLabel.textContent = String(state.platformClients.stats.active_clients || 0);
    el.platformClientsTrialLabel.textContent = String(state.platformClients.stats.trial_clients || 0);
    el.platformClientsBlockedLabel.textContent = String(state.platformClients.stats.blocked_clients || 0);
    el.platformClientsExpiredLabel.textContent = String(state.platformClients.stats.expired_clients || 0);
  }
  if (el.platformClientsTable) {
    if (!state.platformClients.items.length) {
      el.platformClientsTable.innerHTML = '<tr><td colspan="8" class="empty-table">No platform clients found.</td></tr>';
    } else {
      el.platformClientsTable.innerHTML = state.platformClients.items.map((item) => `
        <tr data-client-row="${html(item.admin_id)}">
          <td>${html(item.name || "-")}</td>
          <td>${html(item.email || "-")}</td>
          <td>${html(item.plan_id || "-")}</td>
          <td>${statusPill(item.status || "-")}</td>
          <td>${html(item.trial_days || 0)}</td>
          <td>${html(formatDate(item.subscription_end_date || item.subscription_end))}</td>
          <td>${html(item.server_id || "-")}</td>
          <td>
            <div class="table-actions">
              <button class="ghost-button small-button" data-client-action="${item.status === "blocked" ? "unblock" : "block"}" data-client-id="${html(item.admin_id)}">${item.status === "blocked" ? "Unblock" : "Block"}</button>
              <button class="ghost-button small-button" data-client-action="extend" data-client-id="${html(item.admin_id)}">Extend Trial</button>
              <button class="ghost-button small-button" data-client-action="reset-server" data-client-id="${html(item.admin_id)}">Reset Server</button>
              <button class="ghost-button small-button" data-client-action="delete" data-client-id="${html(item.admin_id)}">Delete</button>
            </div>
          </td>
        </tr>
      `).join("");
      el.platformClientsTable.querySelectorAll("[data-client-action]").forEach((button) => {
        button.addEventListener("click", () => handlePlatformClientAction(button.dataset.clientAction, button.dataset.clientId));
      });
    }
  }
  if (el.systemLogsTable) {
    const logs = state.platformClients.audit_logs || [];
    el.systemLogsTable.innerHTML = logs.length
      ? logs.slice().reverse().slice(0, 100).map((item) => `<tr><td>${html(item.path || "-")}</td><td>${html(item.method || "-")}</td><td>${html(item.status_code || "-")}</td><td>${html(item.admin_id || "-")}</td><td>${html(item.device_id || "-")}</td><td>${html(formatDate(item.timestamp))}</td></tr>`).join("")
      : '<tr><td colspan="6" class="empty-table">No audit logs recorded yet.</td></tr>';
  }
}

function renderMobileBuilds() {
  const status = state.mobileBuilder.status || { status: "idle", progress: 0, version: "", artifact_name: "", error: "", logs: "" };
  const preflight = state.mobileBuilder.preflight || { ready: null, checks: [] };
  const session = state.session || {};
  const backendApi = state.settings?.backendApi || {};
  const authToken = String(session.apiToken || backendApi.apiToken || "").trim();
  const usingFallbackEndpointToken = !String(session.apiToken || "").trim() && Boolean(String(backendApi.apiToken || "").trim());
  const rawLogs = String(status.logs || "");
  const visibleLogs = rawLogs && rawLogs === mobileBuildLogsHiddenSnapshot ? "" : rawLogs;
  if (rawLogs && rawLogs !== mobileBuildLogsHiddenSnapshot) {
    mobileBuildLogsHiddenSnapshot = "";
  }
  if (el.mobileBuildStatusLabel) el.mobileBuildStatusLabel.textContent = status.status || "idle";
  if (el.mobileBuildProgressText) el.mobileBuildProgressText.textContent = `${Number(status.progress || 0)}%`;
  if (el.mobileBuildVersionLabel) el.mobileBuildVersionLabel.textContent = status.version || "-";
  if (el.mobileBuildArtifactLabel) el.mobileBuildArtifactLabel.textContent = status.artifact_name || "-";
  if (el.mobileBuildProgressBar) el.mobileBuildProgressBar.value = Number(status.progress || 0);
  if (el.mobileBuildErrorLabel) {
    el.mobileBuildErrorLabel.textContent = status.error || (mobileAppAlreadyGenerated()
      ? "Mobile app already generated. Branding changes now refresh dynamically in the installed app."
      : "Builds are queued and processed one at a time.");
  }
  if (el.mobileBuildPreflightSummary) {
    const readyLabel = preflight.ready === true ? "Ready to build." : preflight.ready === false ? "Not ready to build." : "Readiness checks have not been loaded yet.";
    const storageLabel = preflight.artifact_storage ? ` Artifact storage: ${preflight.artifact_storage}.` : "";
    const hostLabel = preflight.ready !== null
      ? ` Host mode: ${preflight.worker_enabled_on_host ? "embedded worker" : "queue-only"}`
      : "";
    el.mobileBuildPreflightSummary.textContent = `${readyLabel}${storageLabel}${hostLabel}`;
  }
  if (el.mobileBuildPreflightOutput) {
    const checks = Array.isArray(preflight.checks) ? preflight.checks : [];
    el.mobileBuildPreflightOutput.textContent = checks.length
      ? checks.map((item) => `[${item.ok ? "OK" : item.severity === "info" ? "INFO" : "ERROR"}] ${item.name}: ${item.detail}`).join("\n")
      : "No readiness details yet.";
  }
  if (el.mobileBuildAuthSummary) {
    const authState = authToken ? "Authenticated token present." : "No bearer token available for admin-protected calls.";
    const tenantState = ` Tenant: ${effectiveTenantId()}.`;
    const serverState = ` Server ID: ${session.serverId || "-"}.`;
    el.mobileBuildAuthSummary.textContent = `${authState}${tenantState}${serverState}`;
  }
  if (el.mobileBuildAuthOutput) {
    el.mobileBuildAuthOutput.textContent = [
      `[INFO] session.adminId: ${session.adminId || "-"}`,
      `[INFO] session.role: ${session.role || "-"}`,
      `[INFO] session.tenantId: ${session.tenantId || "-"}`,
      `[INFO] session.adminEmail: ${session.adminEmail || "-"}`,
      `[INFO] session.apiToken_present: ${String(Boolean(String(session.apiToken || "").trim()))}`,
      `[INFO] backendApi.apiToken_present: ${String(Boolean(String(backendApi.apiToken || "").trim()))}`,
      `[INFO] auth_source: ${usingFallbackEndpointToken ? "backend endpoint token fallback" : authToken ? "session api token" : "none"}`,
      `[INFO] session.deviceId: ${session.deviceId || "-"}`,
      `[INFO] session.serverId: ${session.serverId || "-"}`,
      `[INFO] backendApi.url: ${backendApi.url || state.settings?.backendUrl || "-"}`,
      `[INFO] settings.tenantId: ${state.settings?.tenantId || "default"}`,
      `[INFO] effectiveTenantId: ${effectiveTenantId()}`,
    ].join("\n");
  }
  if (el.mobileBuildLogsOutput) {
    const shouldPinToBottom = mobileBuildLogsShouldAutoScroll || isScrolledNearBottom(el.mobileBuildLogsOutput);
    el.mobileBuildLogsOutput.textContent = visibleLogs || "No build logs yet.";
    if (shouldPinToBottom) {
      el.mobileBuildLogsOutput.scrollTop = el.mobileBuildLogsOutput.scrollHeight;
      mobileBuildLogsShouldAutoScroll = true;
    }
  }
  applyMobileBuildLockState();
  if (el.mobileBuildHistoryTable) {
    const history = state.mobileBuilder.history || [];
    el.mobileBuildHistoryTable.innerHTML = history.length
      ? history.map((item) => `
        <tr>
          <td>${html(item.version || "-")}</td>
          <td>${html(item.status || "-")}</td>
          <td>${html(item.progress ?? 0)}%</td>
          <td>${html(formatDate(item.created_at))}</td>
          <td>${html(item.artifact_name || "-")}</td>
          <td>${item.status === "completed" ? `<button class="ghost-button small-button mobile-build-download" data-build-id="${html(item.build_id)}" data-build-file="${html(item.artifact_name || "")}">Download APK</button>` : "-"}</td>
        </tr>
      `).join("")
      : '<tr><td colspan="6" class="empty-table">No mobile builds yet.</td></tr>';
    el.mobileBuildHistoryTable.querySelectorAll(".mobile-build-download").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await window.desktopApi.downloadMobileBuild({ buildId: button.dataset.buildId, fileName: button.dataset.buildFile || "" });
          showToast("APK downloaded.");
        } catch (error) {
          showToast(error.message, true);
        }
      });
    });
  }
}

function isScrolledNearBottom(node, threshold = 24) {
  if (!node) return true;
  return node.scrollHeight - node.scrollTop - node.clientHeight <= threshold;
}

async function copyMobileBuildLogs() {
  const logs = String(state.mobileBuilder.status?.logs || "").trim();
  const text = logs || "No build logs yet.";
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "true");
      helper.style.position = "absolute";
      helper.style.left = "-9999px";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      document.body.removeChild(helper);
    }
    showToast("Build logs copied.");
  } catch (error) {
    showToast("Could not copy build logs.", true);
  }
}

function clearMobileBuildLogsView() {
  mobileBuildLogsHiddenSnapshot = String(state.mobileBuilder.status?.logs || "");
  mobileBuildLogsShouldAutoScroll = true;
  renderMobileBuilds();
  showToast("Build logs cleared from viewer.");
}

function downloadMobileBuildLogs() {
  const logs = String(state.mobileBuilder.status?.logs || "");
  const text = logs || "No build logs yet.\n";
  const buildId = String(state.mobileBuilder.status?.build_id || state.mobileBuilder.activeBuildId || "mobile-build");
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${buildId}.log`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  showToast("Build log downloaded.");
}

function renderApkManagement() {
  const latest = state.apkManagement.latest || {};
  if (el.latestApkVersionLabel) el.latestApkVersionLabel.textContent = latest.version || "-";
  if (el.latestApkPathLabel) el.latestApkPathLabel.textContent = latest.file_path || "-";
  if (el.latestApkForceLabel) el.latestApkForceLabel.textContent = latest.force_update ? "Yes" : "No";
  if (el.apkManagementTable) {
    const items = state.apkManagement.items || [];
    el.apkManagementTable.innerHTML = items.length
      ? items.map((item) => `
        <tr>
          <td>${html(item.version || "-")}</td>
          <td>${html(item.file_path || "-")}</td>
          <td>${html(formatDate(item.uploaded_at))}</td>
          <td>${html(item.is_latest ? "Yes" : "No")}</td>
          <td>${item.is_latest ? "-" : `<button class="ghost-button small-button apk-set-latest" data-apk-id="${html(item.id)}">Set as Latest</button>`}</td>
        </tr>
      `).join("")
      : '<tr><td colspan="5" class="empty-table">No APK versions uploaded yet.</td></tr>';
    el.apkManagementTable.querySelectorAll(".apk-set-latest").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const result = await window.desktopApi.setLatestApk({
            id: button.dataset.apkId,
            force_update: Boolean(el.apkForceUpdateInput?.checked),
          });
          state.apkManagement.items = result.items || state.apkManagement.items;
          state.apkManagement.latest = result.item || state.apkManagement.latest;
          renderApkManagement();
          showToast("Latest APK updated.");
        } catch (error) {
          showToast(error.message, true);
        }
      });
    });
  }
}

function updatePrimaryButtonLabel(updateState) {
  if (updateState.status === "downloaded") return "Restart to Install";
  if (["downloading", "checking"].includes(updateState.status)) return "Downloading...";
  return "Update Now";
}

function renderUpdateCenter() {
  const updateState = state.updateInfo.state || { status: "idle", currentVersion: "" };
  const latest = state.updateInfo.latest || {};
  const currentVersion = updateState.currentVersion || latest.current_version || state.session.appVersion || "";
  if (el.desktopVersionLabel) {
    el.desktopVersionLabel.textContent = currentVersion || "-";
  }
  if (el.footerDesktopVersion) {
    el.footerDesktopVersion.textContent = currentVersion || "-";
  }
  if (el.updateStatusBadge) {
    const labels = {
      idle: "Idle",
      checking: "Checking for updates...",
      "up-to-date": "Up to date",
      available: "Update available",
      required: "Platform update required",
      downloading: "Downloading update...",
      downloaded: "Restart to install",
      error: "Update error",
    };
    el.updateStatusBadge.textContent = labels[updateState.status] || "Idle";
    el.updateStatusBadge.className = `status-chip${updateState.mandatory ? " danger" : ""}`;
  }
  if (el.updateLatestVersionLabel) {
    el.updateLatestVersionLabel.textContent = updateState.latestVersion || latest.latest_version || latest.version || "-";
  }
  if (el.updateMandatoryLabel) {
    el.updateMandatoryLabel.textContent = updateState.mandatory ? "Yes" : "No";
  }
  if (el.updateReleaseDateLabel) {
    el.updateReleaseDateLabel.textContent = updateState.releaseDate || latest.release_date || "-";
  }
  if (el.updateReleaseNotesLabel) {
    el.updateReleaseNotesLabel.textContent = updateState.releaseNotes || latest.release_notes || "No release notes published yet.";
  }
  if (el.updateProgressBar) {
    el.updateProgressBar.value = Math.max(0, Math.min(100, Number(updateState.progressPercent || 0)));
  }
  if (el.updateProgressLabel) {
    if (updateState.status === "downloading") {
      const transferred = Number(updateState.transferred || 0);
      const total = Number(updateState.total || 0);
      const percent = Number(updateState.progressPercent || 0);
      el.updateProgressLabel.textContent = total > 0
        ? `${percent.toFixed(1)}% • ${(transferred / (1024 * 1024)).toFixed(1)}MB / ${(total / (1024 * 1024)).toFixed(1)}MB`
        : `${percent.toFixed(1)}%`;
    } else if (updateState.status === "downloaded") {
      el.updateProgressLabel.textContent = "Update downloaded. Restart the desktop app to install it.";
    } else if (updateState.status === "required") {
      el.updateProgressLabel.textContent = "A mandatory platform update is blocking the dashboard until installation completes.";
    } else if (updateState.status === "error") {
      el.updateProgressLabel.textContent = updateState.error || "Update check failed.";
    } else {
      el.updateProgressLabel.textContent = "The desktop checks in the background every 6 hours.";
    }
  }
  if (el.updatePrimaryButton) {
    el.updatePrimaryButton.textContent = updatePrimaryButtonLabel(updateState);
    el.updatePrimaryButton.disabled = ["checking", "downloading"].includes(updateState.status) || !(updateState.updateAvailable || updateState.mandatory || updateState.status === "downloaded");
  }
  if (el.updateSecondaryButton) {
    el.updateSecondaryButton.classList.toggle("hidden", Boolean(updateState.mandatory) || updateState.status === "downloaded");
  }
  const overlayVisible = Boolean(
    updateState.mandatory
    || ["required", "downloading", "downloaded"].includes(updateState.status)
    || (updateState.status === "available" && !state.updateInfo.dismissed)
  );
  if (el.updateOverlay) {
    el.updateOverlay.classList.toggle("hidden", !overlayVisible);
    el.updateOverlay.classList.toggle("locked", Boolean(updateState.mandatory));
  }
  document.body.classList.toggle("update-locked", Boolean(updateState.mandatory));

  if (el.latestPublishedVersionLabel) {
    el.latestPublishedVersionLabel.textContent = latest.latest_version || latest.version || "-";
  }
  if (el.latestPublishedDateLabel) {
    el.latestPublishedDateLabel.textContent = latest.release_date || "-";
  }
  if (el.latestPublishedDownloadLabel) {
    el.latestPublishedDownloadLabel.textContent = latest.download_name || latest.download_url || "-";
  }
  if (el.latestPublishedMandatoryLabel) {
    el.latestPublishedMandatoryLabel.textContent = latest.mandatory ? "Yes" : "No";
  }
  if (el.updateHistoryTable) {
    const history = state.updateInfo.history || [];
    el.updateHistoryTable.innerHTML = history.length
      ? history.map((item) => `<tr><td>${html(item.version || "-")}</td><td>${html(item.date || "-")}</td><td>${html((item.platforms || []).join(", ") || "-")}</td><td>${html(item.mandatory ? "Yes" : "No")}</td><td>${html(item.notes || "-")}</td></tr>`).join("")
      : '<tr><td colspan="5" class="empty-table">No published versions yet.</td></tr>';
  }
}

function renderSetupWizard() {
  const setup = state.setup || { setup_completed: true, steps: [] };
  el.setupWizardCard.classList.toggle("hidden", Boolean(setup.setup_completed));
  el.setupStepList.innerHTML = (setup.steps || []).map((step) => `
    <article class="setup-step ${step.completed ? "done" : ""}">
      <strong>${html(step.label || step.id || "Step")}</strong>
      <div class="subtle">${step.completed ? "Completed" : "Pending"}</div>
    </article>
  `).join("");
  el.setupMobileToken.textContent = setup.mobile_api_token || "-";
  el.setupServerId.textContent = setup.server_id || "-";
}

function renderServerStatus() {
  const runtime = state.runtimeStatus;
  if (!runtime) {
    el.serverStatusPanel.innerHTML = '<div class="empty-state">Runtime status not loaded yet.</div>';
    return;
  }
  const rows = [
    ["Mode", runtime.mode || "idle"],
    ["Backend URL", runtime.url || endpointConfig("backend").url],
    ["Reachable", runtime.reachable ? "Yes" : "No"],
    ["Managed Process", runtime.managed ? "Yes" : "No"],
    ["PID", runtime.pid || "-"],
    ["Python", runtime.python?.available ? (runtime.python.executable || "Available") : "Missing"],
    ["Started At", formatDate(runtime.startedAt)],
    ["Log Path", runtime.logPath || "-"],
    ["Last Error", runtime.lastError || "None"],
  ];
  el.serverStatusPanel.innerHTML = rows.map(([label, value]) => `<div class="security-pill"><span class="detail-label">${html(label)}</span><strong>${html(value)}</strong></div>`).join("");
}

async function readFileAsDataUrl(file) {
  if (!file) return "";
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read logo file."));
    reader.readAsDataURL(file);
  });
}

async function uploadSelectedLogo(folder, nameHint) {
  const file = el.entityLogoFileInput.files?.[0];
  if (!file) return "";
  const result = await window.desktopApi.uploadAsset({ folder, name_hint: nameHint, data_url: await readFileAsDataUrl(file) });
  return result.url || "";
}

function previewEntityLogo(url) {
  el.entityLogoPreview.dataset.logoUrl = url || "";
  el.entityLogoPreview.classList.toggle("hidden", !url);
  el.entityLogoPreview.innerHTML = url ? `<div class="asset-preview-content">${logoMarkup(url, "logo", true)}<div><strong>Saved logo</strong><div class="subtle">${html(url)}</div></div></div>` : "";
}

function renderCompetitionClubAssignments(selectedClubIds = []) {
  if (!el.entityCompetitionClubAssignments) return;
  const nationId = el.entityNationSelect.value || state.selectedNationId || state.nations[0]?.id || "";
  const clubs = state.clubs.filter((item) => item.nation_id === nationId);
  const selected = new Set((selectedClubIds || []).map((item) => String(item)));
  if (!clubs.length) {
    el.entityCompetitionClubAssignments.innerHTML = '<div class="empty-state">Create clubs for this nation first.</div>';
    return;
  }
  el.entityCompetitionClubAssignments.innerHTML = clubs.map((club) => `
    <label class="toggle">
      <input type="checkbox" data-club-assignment value="${html(club.id)}" ${selected.has(String(club.id)) ? "checked" : ""}>
      <span>${html(club.name)}</span>
    </label>
  `).join("");
}

function selectedCompetitionClubIds() {
  if (!el.entityCompetitionClubAssignments) return [];
  return [...el.entityCompetitionClubAssignments.querySelectorAll("input[data-club-assignment]:checked")]
    .map((input) => String(input.value || "").trim())
    .filter(Boolean);
}

function populateEntitySelectors() {
  el.entityNationSelect.innerHTML = optionMarkup(state.nations, el.entityNationSelect.value || state.selectedNationId || state.nations[0]?.id || "");
  const nationId = el.entityNationSelect.value || state.selectedNationId || state.nations[0]?.id || "";
  const competitions = state.competitions.filter((item) => item.nation_id === nationId);
  if (el.entityClubCompetitionSelect) el.entityClubCompetitionSelect.innerHTML = optionMarkup(competitions, el.entityClubCompetitionSelect.value || "", true);
  if (el.entityTypeInput.value === "competition") {
    const selectedClubIds = selectedCompetitionClubIds();
    renderCompetitionClubAssignments(selectedClubIds);
  }
}

function openEntityModal(type, item = null) {
  if (type === "competition" && !state.nations.length) {
    showToast("Create a nation first.", true);
    return;
  }
  el.entityTypeInput.value = type;
  el.entityIdInput.value = item?.id || "";
  el.entityNameInput.value = item?.name || "";
  el.entityLogoFileInput.value = "";
  previewEntityLogo(item?.logo_url || "");
  el.entityModalEyebrow.textContent = type === "nation" ? "Nation" : type === "competition" ? "Competition" : "Club";
  el.entityModalTitle.textContent = item ? `Edit ${item.name}` : `New ${type}`;
  el.entityNationField.classList.toggle("hidden", type === "nation" || type === "club");
  el.entityCompetitionTypeField.classList.toggle("hidden", type !== "competition");
  el.entityCompetitionParticipantField.classList.toggle("hidden", type !== "competition");
  el.entityCompetitionClubAssignmentsField.classList.toggle("hidden", type !== "competition");
  el.entityClubCompetitionField.classList.add("hidden");
  el.deleteEntityButton.disabled = !item?.id;
  el.deleteEntityButton.dataset.id = item?.id || "";
  el.deleteEntityButton.dataset.type = type;
  populateEntitySelectors();
  if (type === "competition") {
    el.entityNationSelect.value = item?.nation_id || state.selectedNationId || state.nations[0]?.id || "";
    el.entityCompetitionTypeSelect.value = item?.type || "league";
    el.entityCompetitionParticipantSelect.value = item?.participant_type || "clubs";
    el.entityCompetitionClubAssignmentsField.classList.toggle("hidden", el.entityCompetitionParticipantSelect.value === "nations");
    renderCompetitionClubAssignments(item?.club_ids || []);
  }
  if (type === "club") {
    el.entityNationSelect.value = item?.nation_id || "";
  }
  setModalVisibility(el.entityModal, true);
}

async function refreshMetadata() {
  const [nations, competitions, clubs] = await Promise.all([window.desktopApi.fetchNations(), window.desktopApi.fetchCompetitions(), window.desktopApi.fetchClubs({})]);
  applyCatalogState({
    nations: nations.items,
    competitions: competitions.items,
    competitionClubLinks: competitions.competition_club_links,
    clubs: clubs.items,
  });
  hydrateSettings();
  renderMetadataLists();
  renderApprovalPanel();
}

async function refreshApprovedMatches() {
  const payload = await window.desktopApi.fetchApprovedStreams();
  state.approvedMatches = payload.items || [];
  hydrateSettings();
  renderApprovedMatches();
  renderApprovalPanel();
  renderPreview();
}

async function refreshStreams() {
  const payload = await window.desktopApi.fetchStreams(state.selectedStreamProviderId || "");
  state.activeProviders = payload.providers || [];
  state.selectedStreamProviderId = payload.selectedProviderId || state.activeProviders[0]?.id || "";
  state.streams = payload.items || [];
  state.groups = normalizeProviderGroups(payload.groups || [], state.streams);
  console.log("Groups received:", state.groups);
  if (!state.selectedGroup || !state.groups.find((group) => group.id === state.selectedGroup)) state.selectedGroup = state.groups[0]?.id || null;
  if (state.selectedChannel && !state.streams.find((item) => String(item.id || item.stream_id) === String(state.selectedChannel.id || state.selectedChannel.stream_id))) {
    state.selectedChannel = null;
  }
  renderGroups();
  renderChannels();
  renderApprovalPanel();
  renderPreview();
}

async function refreshUsers() {
  if (!isMasterRole()) {
    state.users = [];
    state.onlineUsers = [];
    hydrateSettings();
    renderUsers();
    renderOnlineUsers();
    return;
  }
  const [usersPayload, onlinePayload] = await Promise.all([window.desktopApi.fetchUsers(), window.desktopApi.fetchOnlineUsers()]);
  state.users = usersPayload.items || [];
  state.onlineUsers = onlinePayload.items || [];
  state.userStats = usersPayload.stats || state.userStats;
  hydrateSettings();
  renderUsers();
  renderOnlineUsers();
}

async function refreshAnalytics() {
  const [livePayload, streamsPayload, topMatchesPayload, topCompetitionsPayload, dailyPayload, countriesPayload] = await Promise.all([window.desktopApi.fetchAnalyticsLive(), window.desktopApi.fetchAnalyticsStreams(), window.desktopApi.fetchTopMatches(), window.desktopApi.fetchTopCompetitions(), window.desktopApi.fetchDailyViewers(), window.desktopApi.fetchCountries()]);
  state.analytics.live = livePayload || state.analytics.live;
  state.analytics.streams = streamsPayload.items || [];
  state.analytics.topMatches = topMatchesPayload.items || [];
  state.analytics.topCompetitions = topCompetitionsPayload.items || [];
  state.analytics.dailyViewers = dailyPayload.items || [];
  state.analytics.countries = countriesPayload.items || [];
  renderAnalytics();
}

async function refreshPlatformClients() {
  if (!isMasterRole()) {
    state.platformClients = { items: [], stats: {}, audit_logs: [] };
    renderPlatformClients();
    return;
  }
  const [clientsPayload, dashboardPayload] = await Promise.all([
    window.desktopApi.fetchPlatformClients().catch(() => ({ items: [], stats: {} })),
    window.desktopApi.fetchWhiteLabelInstalls().catch(() => ({ audit_logs: [] })),
  ]);
  state.platformClients = {
    items: clientsPayload.items || [],
    stats: clientsPayload.stats || {},
    audit_logs: dashboardPayload.audit_logs || [],
  };
  renderPlatformClients();
}

async function refreshMobileBuilds() {
  const historyPayload = await window.desktopApi.fetchMobileBuildHistory().catch(() => ({ items: [] }));
  const history = historyPayload.items || [];
  if (historyPayload.status) {
    state.branding = {
      ...(state.branding || {}),
      mobile_app_generated: historyPayload.status.mobile_app_generated === true || mobileAppAlreadyGenerated(),
      mobile_app_package_id: historyPayload.status.mobile_app_package_id || state.branding?.mobile_app_package_id || "",
      mobile_app_created_at: historyPayload.status.mobile_app_created_at || state.branding?.mobile_app_created_at || "",
    };
  }
  state.mobileBuilder.history = history;
  const active = history.find((item) => ["queued", "building"].includes(String(item.status || ""))) || history[0] || null;
  state.mobileBuilder.activeBuildId = active?.build_id || "";
  if (historyPayload.status) {
    state.mobileBuilder.status = historyPayload.status;
  } else if (state.mobileBuilder.activeBuildId) {
    state.mobileBuilder.status = await window.desktopApi.fetchMobileBuildStatus(state.mobileBuilder.activeBuildId).catch(() => state.mobileBuilder.status);
  } else {
    state.mobileBuilder.status = { status: "idle", progress: 0, version: "", artifact_name: "", error: "", logs: "" };
  }
  renderMobileBuilds();
}

async function refreshMobileBuildPreflight() {
  state.mobileBuilder.preflight = await window.desktopApi.fetchMobileBuildPreflight().catch(() => ({
    ready: false,
    checks: [{ name: "preflight", ok: false, severity: "error", detail: "Could not load mobile build readiness from backend." }],
    artifact_storage: "",
    worker_enabled_on_host: false,
  }));
  renderMobileBuilds();
}

function clearMobileBuildPreflight() {
  state.mobileBuilder.preflight = {
    ready: null,
    checks: [],
    artifact_storage: "",
    worker_enabled_on_host: false,
  };
  renderMobileBuilds();
}

async function refreshApkManagement() {
  if (!isMasterRole()) {
    state.apkManagement = { items: [], latest: null };
    renderApkManagement();
    return;
  }
  const payload = await window.desktopApi.fetchApkVersions().catch(() => ({ items: [] }));
  const items = payload.items || [];
  state.apkManagement.items = items;
  state.apkManagement.latest = items.find((item) => item.is_latest) || items[0] || null;
  renderApkManagement();
}

async function refreshUpdatesPanel() {
  const [latest, history, updateState] = await Promise.all([
    window.desktopApi.fetchLatestUpdateMeta().catch(() => state.updateInfo.latest),
    isMasterRole() ? window.desktopApi.fetchUpdateHistory().catch(() => state.updateInfo.history) : Promise.resolve(state.updateInfo.history),
    window.desktopApi.getUpdateState().catch(() => state.updateInfo.state),
  ]);
  state.updateInfo.latest = latest || state.updateInfo.latest;
  state.updateInfo.history = history || state.updateInfo.history;
  state.updateInfo.state = updateState || state.updateInfo.state;
  renderUpdateCenter();
}

async function refreshSecurity() {
  state.security = await window.desktopApi.fetchSecurityDashboard();
  renderSecurity();
}

async function refreshBackups() {
  state.backup = await window.desktopApi.fetchBackupStatus();
  hydrateSettings();
  renderBackups();
}

async function refreshSetupStatus() {
  state.setup = await window.desktopApi.fetchSetupStatus().catch(() => state.setup);
  renderSetupWizard();
}

async function refreshRuntimeStatus() {
  state.runtimeStatus = await window.desktopApi.fetchRuntimeStatus().catch(() => null);
  renderServerStatus();
}

async function refreshTenantsAndBranding() {
  const [tenantsPayload, brandingPayload] = await Promise.all([window.desktopApi.fetchTenants().catch(() => ({ items: [] })), window.desktopApi.fetchBranding().catch(() => null)]);
  state.tenants = tenantsPayload.items || [];
  state.branding = brandingPayload;
  hydrateSettings();
}

async function refreshMasterLive() {
  if (!isMasterRole()) {
    state.masterLive = { status: "idle", version: null, streams: { items: [] }, liveScores: { matches: [] }, standings: { standings: [] }, fixtures: { matches: [] }, lastUpdatedAt: "", error: "" };
    renderMasterLive();
    return;
  }
  state.masterLive = await window.desktopApi.getMasterLiveState().catch(() => state.masterLive);
  renderMasterLive();
}

async function refreshVisibleSectionData(section = state.activeSection) {
  switch (section) {
    case "analytics":
      await refreshAnalytics();
      return;
    case "security":
      await refreshSecurity();
      return;
    case "backups":
      await refreshBackups();
      return;
    case "mobile_builder":
      await refreshMobileBuilds();
      await refreshMobileBuildPreflight();
      if (isMasterRole()) {
        await refreshApkManagement();
      }
      return;
    case "platform_clients":
      if (isMasterRole()) {
        await refreshPlatformClients();
      }
      return;
    case "dashboard":
      await Promise.all([
        refreshAnalytics().catch(() => {}),
        refreshRuntimeStatus().catch(() => {}),
        refreshUpdatesPanel().catch(() => {}),
        isMasterRole() ? refreshMasterLive().catch(() => {}) : Promise.resolve(),
      ]);
      return;
    default:
      return;
  }
}

async function refreshAll() {
  hydrateSettings();
  renderProviders();
  applyRoleAccess();
  const jobs = [
    refreshTenantsAndBranding(),
    refreshMetadata(),
    refreshApprovedMatches(),
    refreshStreams(),
    refreshUsers(),
    refreshSetupStatus(),
    refreshRuntimeStatus(),
    refreshUpdatesPanel(),
    refreshVisibleSectionData(),
  ];
  await Promise.all(jobs);
}
async function runUserAction(task, successMessage) {
  try {
    await task();
    await refreshUsers();
    showToast(successMessage);
  } catch (error) {
    showToast(error.message, true);
  }
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file) return resolve("");
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Failed to read file."));
    reader.readAsDataURL(file);
  });
}

async function handlePlatformClientAction(action, adminId) {
  try {
    if (action === "block") await window.desktopApi.blockPlatformClient(adminId);
    if (action === "unblock") await window.desktopApi.unblockPlatformClient(adminId);
    if (action === "reset-server") await window.desktopApi.resetPlatformClientServer(adminId);
    if (action === "delete") await window.desktopApi.deletePlatformClient(adminId);
    if (action === "extend") {
      const days = window.prompt("Extend trial by how many days?", "3");
      if (days === null) return;
      await window.desktopApi.extendPlatformClientTrial({ adminId, days: Number(days || 0) });
    }
    await refreshPlatformClients();
    showToast("Platform client updated.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function logout() {
  if (dashboardPollIntervalId) {
    clearInterval(dashboardPollIntervalId);
    dashboardPollIntervalId = null;
  }
  try {
    await window.desktopApi.logout();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function renameUser(user) {
  const nextName = window.prompt("Admin display name", user.admin_name || user.device_name || "");
  if (nextName === null) return;
  return runUserAction(() => window.desktopApi.renameUser({ device_id: user.device_id, admin_name: nextName.trim() }), "Admin name updated.");
}

async function extendUser(user) {
  const days = window.prompt("Extend access by how many days?", "30");
  if (days === null) return;
  return runUserAction(() => window.desktopApi.extendUser({ device_id: user.device_id, days: Number(days || 0) }), "Expiry extended.");
}

async function submitApproval() {
  if (!state.selectedChannel) return showToast("Select a stream first.", true);
  try {
    await window.desktopApi.approveStream({ stream_id: String(state.selectedChannel.id || state.selectedChannel.stream_id), nation_id: el.approveNationSelect.value, competition_id: el.approveCompetitionSelect.value, home_club_id: el.approveHomeClubSelect.value, away_club_id: el.approveAwayClubSelect.value, kickoff_label: el.approveKickoffInput.value.trim() });
    await refreshApprovedMatches();
    renderChannels();
    renderPreview();
    showToast("Match mapping saved.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function handleMenuAction(payload) {
  if (!payload) return;
  if (payload.section) setActiveSection(payload.section);
  if (payload.action === "logout") return void logout();
  if (payload.action === "backup-now") return void el.backupNowButton.click();
  if (payload.action === "server-status" || payload.action === "system-information") return void refreshRuntimeStatus().then(() => showToast("Server status refreshed.")).catch((error) => showToast(error.message, true));
  if (payload.action === "check-for-updates") return void window.desktopApi.checkForUpdates().catch((error) => showToast(error.message, true));
  if (payload.action === "tenant-login") return void el.tenantUsernameInput.focus();
}

async function bootstrap() {
  const bootstrapData = await window.desktopApi.getBootstrap();
  state.providers = bootstrapData.providers || [];
  state.activeProvider = bootstrapData.activeProvider || null;
  state.settings = { ...state.settings, ...(bootstrapData.settings || {}) };
  state.session = bootstrapData.session || {};
  state.updateInfo.state = bootstrapData.updateState || state.updateInfo.state;
  state.masterLive = bootstrapData.masterLiveState || state.masterLive;
  applyRoleAccess();
  state.selectedProviderId = state.activeProvider?.id || state.providers[0]?.id || null;
  populateProviderForm(state.providers.find((item) => item.id === state.selectedProviderId) || null);
  setActiveSection(state.activeSection);
  setCatalogTab(state.activeCatalogTab);
  renderMasterLive();
  await refreshAll();
  await fetchBackendConnectivitySnapshot();
}

el.navItems.forEach((item) => item.addEventListener("click", () => setActiveSection(item.dataset.section)));
el.navTargets.forEach((button) => button.addEventListener("click", () => setActiveSection(button.dataset.navTarget)));
el.catalogTabs.forEach((button) => button.addEventListener("click", () => setCatalogTab(button.dataset.catalogTab)));

el.openProviderManagerButton.addEventListener("click", () => setModalVisibility(el.providerModal, true));
el.openProviderManagerButtonDuplicate.addEventListener("click", () => setModalVisibility(el.providerModal, true));
el.closeProviderModalButton.addEventListener("click", () => setModalVisibility(el.providerModal, false));
el.providerTypeSelect.addEventListener("change", updateProviderTypeVisibility);
el.newProviderButton.addEventListener("click", () => { state.selectedProviderId = null; populateProviderForm(); renderProviders(); });

el.providerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await window.desktopApi.saveProvider({ id: el.providerIdInput.value || null, name: el.providerNameInput.value, type: el.providerTypeSelect.value, xtreamServerUrl: el.xtreamServerUrlInput.value, xtreamUsername: el.xtreamUsernameInput.value, xtreamPassword: el.xtreamPasswordInput.value, m3uPlaylistUrl: el.m3uPlaylistUrlInput.value, cacheTtlSeconds: el.cacheTtlInput.value, isActive: el.providerActiveCheckbox.checked });
    state.providers = result.providers || [];
    state.activeProvider = result.activeProvider || null;
    state.selectedProviderId = result.provider?.id || state.selectedProviderId;
    populateProviderForm(state.providers.find((item) => item.id === state.selectedProviderId) || null);
    renderProviders();
    hydrateSettings();
    await refreshStreams();
    showToast("Provider saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.deleteProviderButton.addEventListener("click", async () => {
  const providerId = Number(el.providerIdInput.value || 0);
  if (!providerId) return;
  try {
    const result = await window.desktopApi.deleteProvider(providerId);
    state.providers = result.providers || [];
    state.activeProvider = result.activeProvider || null;
    state.selectedProviderId = state.activeProvider?.id || state.providers[0]?.id || null;
    populateProviderForm(state.providers.find((item) => item.id === state.selectedProviderId) || null);
    renderProviders();
    hydrateSettings();
    await refreshStreams();
    showToast("Provider deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.saveBackendSettingsButton.addEventListener("click", async () => {
  try {
    state.settings = await window.desktopApi.saveSettings({
      ...state.settings,
      adminUsername: el.adminUsernameInput.value,
      adminPassword: el.adminPasswordInput.value,
      tenantId: el.tenantSelect.value || "default",
      tenantUsername: el.tenantUsernameInput.value,
      tenantPassword: el.tenantPasswordInput.value,
      chromePreviewApiMode: "backend",
    });
    hydrateSettings();
    await refreshRuntimeStatus();
    showToast("API and tenant settings saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.tenantSelect.addEventListener("change", async () => {
  state.settings = await window.desktopApi.saveSettings({ ...state.settings, tenantId: el.tenantSelect.value || "default" });
  hydrateSettings();
  await refreshAll();
});

el.streamProviderSelect?.addEventListener("change", async () => {
  state.selectedStreamProviderId = el.streamProviderSelect.value || "";
  state.selectedGroup = null;
  state.selectedChannel = null;
  try {
    await refreshStreams();
  } catch (error) {
    showToast(error.message, true);
  }
});

el.tenantLoginButton.addEventListener("click", async () => {
  try {
    const result = await window.desktopApi.tenantLogin({ tenant_id: el.tenantSelect.value || "default", username: el.tenantUsernameInput.value, password: el.tenantPasswordInput.value });
    state.settings = { ...state.settings, ...result };
    await refreshAll();
    showToast("Tenant login successful.");
  } catch (error) {
    showToast(error.message, true);
  }
});

async function handleApiEndpointAction(kind, action) {
  if (!isMasterRole()) {
    showToast("Only master admins can manage platform API endpoints.", true);
    return;
  }
  const endpoint = kind === "public"
    ? { url: el.publicApiUrlInput.value.trim(), apiToken: el.publicApiTokenInput.value.trim() }
    : { url: el.backendApiUrlInput.value.trim(), apiToken: el.backendApiTokenInput.value.trim() };
  try {
    if (action === "test") {
      await window.desktopApi.testApiEndpoint({ kind, ...endpoint });
      showToast(`${kind === "public" ? "Public" : "Backend"} API test succeeded.`);
      return;
    }
    if (action === "connect") {
      const result = await window.desktopApi.connectApiEndpoint({ kind, ...endpoint });
      state.settings = result.settings || state.settings;
      hydrateSettings();
      if (result.error) {
        showToast(result.error, true);
        return;
      }
      await refreshRuntimeStatus();
      showToast(`${kind === "public" ? "Public" : "Backend"} API connected.`);
      return;
    }
    if (action === "disconnect") {
      const result = await window.desktopApi.disconnectApiEndpoint({ kind });
      state.settings = result.settings || state.settings;
      hydrateSettings();
      await refreshRuntimeStatus();
      showToast(`${kind === "public" ? "Public" : "Backend"} API disconnected.`);
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

el.backendApiConnectButton?.addEventListener("click", () => handleApiEndpointAction("backend", "connect"));
el.backendApiDisconnectButton?.addEventListener("click", () => handleApiEndpointAction("backend", "disconnect"));
el.backendApiTestButton?.addEventListener("click", () => handleApiEndpointAction("backend", "test"));
el.publicApiConnectButton?.addEventListener("click", () => handleApiEndpointAction("public", "connect"));
el.publicApiDisconnectButton?.addEventListener("click", () => handleApiEndpointAction("public", "disconnect"));
el.publicApiTestButton?.addEventListener("click", () => handleApiEndpointAction("public", "test"));
el.backendApiUrlInput?.addEventListener("input", renderApiEndpointState);
el.backendApiTokenInput?.addEventListener("input", renderApiEndpointState);
el.publicApiUrlInput?.addEventListener("input", renderApiEndpointState);
el.publicApiTokenInput?.addEventListener("input", renderApiEndpointState);
el.chromePreviewApiToggle?.addEventListener("change", async () => {
  try {
    state.settings = await window.desktopApi.saveSettings({
      ...state.settings,
      chromePreviewApiMode: "backend",
    });
    hydrateSettings();
    showToast("Chrome preview now uses Backend API.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.saveBrandingButton.addEventListener("click", async () => {
  try {
    const [logoDataUrl, iconDataUrl] = await Promise.all([
      fileToDataUrl(el.brandingLogoFileInput?.files?.[0]),
      fileToDataUrl(el.brandingIconFileInput?.files?.[0]),
    ]);
    let currentBranding = state.branding?.branding || {};
    if (logoDataUrl) {
      const upload = await window.desktopApi.uploadBrandingAsset({ kind: "logo", dataUrl: logoDataUrl });
      currentBranding = { ...currentBranding, ...(upload.branding || {}), logo_url: upload.url || currentBranding.logo_url };
    }
    if (iconDataUrl) {
      const upload = await window.desktopApi.uploadBrandingAsset({ kind: "icon", dataUrl: iconDataUrl });
      currentBranding = { ...currentBranding, ...(upload.branding || {}), icon_url: upload.url || currentBranding.icon_url };
    }
    const result = await window.desktopApi.saveBranding({ app_name: el.brandingAppNameInput.value.trim(), primary_color: el.brandingPrimaryColorInput.value.trim(), secondary_color: el.brandingSecondaryColorInput.value.trim() || el.brandingAccentColorInput.value.trim(), accent_color: el.brandingSecondaryColorInput.value.trim() || el.brandingAccentColorInput.value.trim(), surface_color: el.brandingSurfaceColorInput.value.trim(), background_color: el.brandingBackgroundColorInput.value.trim(), text_color: el.brandingTextColorInput.value.trim(), logo_url: currentBranding.logo_url || "", logo_file: currentBranding.logo_url || "", icon_url: currentBranding.icon_url || "" });
    state.branding = { ...(state.branding || {}), branding: result.branding || {} };
    hydrateSettings();
    showToast("Branding saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

async function saveMobileAppSettings(showSuccessToast = false) {
  const [logoDataUrl, splashDataUrl] = await Promise.all([
    fileToDataUrl(el.mobileBuilderLogoInput?.files?.[0]),
    fileToDataUrl(el.mobileBuilderSplashInput?.files?.[0]),
  ]);
  let currentBranding = state.branding?.branding || {};
  if (logoDataUrl) {
    const upload = await window.desktopApi.uploadBrandingAsset({ kind: "logo", dataUrl: logoDataUrl });
    currentBranding = { ...currentBranding, ...(upload.branding || {}), logo_url: upload.url || currentBranding.logo_url, logo_file: upload.url || currentBranding.logo_file };
  }
  if (splashDataUrl) {
    const upload = await window.desktopApi.uploadBrandingAsset({ kind: "splash", dataUrl: splashDataUrl });
    currentBranding = { ...currentBranding, ...(upload.branding || {}), splash_screen: upload.url || currentBranding.splash_screen };
  }
  const brandingSave = await window.desktopApi.saveBranding({
    app_name: el.mobileBuilderAppNameInput.value.trim(),
    package_name: el.mobileBuilderPackageInput.value.trim(),
    primary_color: el.mobileBuilderPrimaryColorInput.value.trim(),
    secondary_color: el.mobileBuilderSecondaryColorInput.value.trim(),
    accent_color: el.mobileBuilderSecondaryColorInput.value.trim(),
    server_url: el.mobileBuilderServerUrlInput.value.trim() || endpointConfig("public").url || DEFAULT_API_URL,
    api_base_url: el.mobileBuilderServerUrlInput.value.trim() || endpointConfig("public").url || DEFAULT_API_URL,
    logo_url: currentBranding.logo_url || "",
    logo_file: currentBranding.logo_file || currentBranding.logo_url || "",
    splash_screen: currentBranding.splash_screen || "",
  });
  state.branding = { ...(state.branding || {}), branding: brandingSave.branding || {} };
  hydrateSettings();
  if (showSuccessToast) {
    showToast("Mobile app settings saved.");
  }
}

el.saveMobileAppSettingsButton?.addEventListener("click", async () => {
  try {
    await saveMobileAppSettings(true);
  } catch (error) {
    showToast(error.message, true);
  }
});

el.generateMobileApkButton?.addEventListener("click", async () => {
  try {
    await refreshMobileBuildPreflight();
    if (state.mobileBuilder.preflight?.ready === false) {
      showToast("Mobile build is not ready yet. Open the readiness panel for the failing checks.", true);
      return;
    }
    if (mobileAppAlreadyGenerated()) {
      showToast("Mobile application already created. You can modify branding but cannot generate a new app.", true);
      return;
    }
    await saveMobileAppSettings(false);
    const build = await window.desktopApi.createMobileBuild();
    state.mobileBuilder.activeBuildId = build.build_id || "";
    await refreshMobileBuilds();
    hydrateSettings();
    setActiveSection("mobile_builder");
    showToast("Mobile build queued.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.cancelMobileBuildButton?.addEventListener("click", async () => {
  const buildId = state.mobileBuilder.activeBuildId || "";
  if (!buildId) {
    showToast("No active mobile build to cancel.", true);
    return;
  }
  try {
    await window.desktopApi.cancelMobileBuild(buildId);
    await refreshMobileBuilds();
    hydrateSettings();
    showToast("Mobile build cancellation requested.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.refreshMobileBuildsButton?.addEventListener("click", async () => {
  try {
    await Promise.all([refreshMobileBuilds(), refreshMobileBuildPreflight()]);
    showToast("Mobile builds refreshed.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.refreshMobileBuildPreflightButton?.addEventListener("click", async () => {
  try {
    await refreshMobileBuildPreflight();
    showToast("Build readiness refreshed.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.clearMobileBuildPreflightButton?.addEventListener("click", () => {
  clearMobileBuildPreflight();
  showToast("Build readiness cleared.");
});

el.mobileBuildLogsOutput?.addEventListener("scroll", () => {
  mobileBuildLogsShouldAutoScroll = isScrolledNearBottom(el.mobileBuildLogsOutput);
});

el.clearMobileBuildLogsButton?.addEventListener("click", () => {
  clearMobileBuildLogsView();
});

el.copyMobileBuildLogsButton?.addEventListener("click", async () => {
  await copyMobileBuildLogs();
});

el.downloadMobileBuildLogsButton?.addEventListener("click", () => {
  downloadMobileBuildLogs();
});

el.uploadApkButton?.addEventListener("click", async () => {
  const apkFile = el.apkFileInput?.files?.[0];
  const version = String(el.apkVersionInput?.value || "").trim();
  if (!apkFile) return showToast("Choose an APK file first.", true);
  if (!version) return showToast("Enter the APK version first.", true);
  try {
    const result = await window.desktopApi.uploadApk({
      version,
      filename: apkFile.name,
      file_data: await readFileAsDataUrl(apkFile),
    });
    state.apkManagement.items = result.items || state.apkManagement.items;
    state.apkManagement.latest = (result.items || []).find((item) => item.is_latest) || result.item || state.apkManagement.latest;
    if (el.apkFileInput) el.apkFileInput.value = "";
    if (el.apkVersionInput) el.apkVersionInput.value = "";
    renderApkManagement();
    showToast("APK uploaded.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.saveBackupSettingsButton.addEventListener("click", async () => {
  try {
    state.settings = await window.desktopApi.saveSettings({ ...state.settings, backupPath: el.backupPathInput.value.trim(), backupSchedule: el.backupScheduleSelect.value, backupRetention: el.backupRetentionInput.value.trim(), cloudBackupEnabled: el.cloudBackupEnabledInput.value, s3Bucket: el.s3BucketInput.value.trim(), s3Prefix: el.s3PrefixInput.value.trim(), awsRegion: el.awsRegionInput.value.trim() });
    await refreshBackups();
    showToast("Backup settings saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.completeSetupButton.addEventListener("click", async () => {
  try {
    state.setup = await window.desktopApi.completeSetup();
    await refreshSetupStatus();
    showToast("Setup wizard completed.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.refreshBackupButton.addEventListener("click", async () => { try { await refreshBackups(); showToast("Backups refreshed."); } catch (error) { showToast(error.message, true); } });
el.backupNowButton.addEventListener("click", async () => { try { await window.desktopApi.runBackupNow(); await refreshBackups(); showToast("Backup completed."); } catch (error) { showToast(error.message, true); } });
el.syncProviderButton.addEventListener("click", async () => { try { state.settings = await window.desktopApi.saveSettings({ ...state.settings, adminUsername: el.adminUsernameInput.value, adminPassword: el.adminPasswordInput.value, chromePreviewApiMode: "backend" }); await window.desktopApi.syncActiveProvider(state.selectedStreamProviderId || ""); await refreshStreams(); await refreshApprovedMatches(); showToast("Active provider synced and refreshed."); } catch (error) { showToast(error.message, true); } });
el.refreshStreamsButton.addEventListener("click", async () => { try { await refreshAll(); showToast("Backend data refreshed."); } catch (error) { showToast(error.message, true); } });
el.refreshUsersButton.addEventListener("click", async () => { try { await refreshUsers(); showToast("Users refreshed."); } catch (error) { showToast(error.message, true); } });
el.refreshAnalyticsButton.addEventListener("click", async () => { try { await refreshAnalytics(); showToast("Analytics refreshed."); } catch (error) { showToast(error.message, true); } });
el.analyticsRefreshButtonDuplicate.addEventListener("click", async () => { try { await refreshAnalytics(); showToast("Analytics refreshed."); } catch (error) { showToast(error.message, true); } });
el.refreshSecurityButton.addEventListener("click", async () => { try { await refreshSecurity(); showToast("Security dashboard refreshed."); } catch (error) { showToast(error.message, true); } });
el.openWhiteLabelDashboardButton.addEventListener("click", async () => { try { await window.desktopApi.openWhiteLabelDashboard(); } catch (error) { showToast(error.message, true); } });
el.refreshPlatformClientsButton?.addEventListener("click", async () => { try { await refreshPlatformClients(); showToast("Platform clients refreshed."); } catch (error) { showToast(error.message, true); } });
el.manualUpdateCheckButton.addEventListener("click", async () => { try { state.updateInfo.dismissed = false; await window.desktopApi.checkForUpdates(); await refreshUpdatesPanel(); } catch (error) { showToast(error.message, true); } });
el.updatePrimaryButton?.addEventListener("click", async () => {
  try {
    const updateState = state.updateInfo.state || {};
    if (updateState.status === "downloaded") {
      await window.desktopApi.installUpdate();
      return;
    }
    await window.desktopApi.downloadUpdate();
  } catch (error) {
    showToast(error.message, true);
  }
});
el.updateSecondaryButton?.addEventListener("click", () => {
  if (state.updateInfo.state?.mandatory) return;
  state.updateInfo.dismissed = true;
  if (el.updateOverlay) el.updateOverlay.classList.add("hidden");
});
el.publishUpdateForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const installer = el.updateInstallerInput?.files?.[0];
  if (!installer) return showToast("Choose an installer file first.", true);
  if (installer.size > 500 * 1024 * 1024) return showToast("Installer must be 500MB or smaller.", true);
  try {
    const result = await window.desktopApi.publishSystemUpdate({
      version: el.updateVersionInput.value.trim(),
      filename: installer.name,
      file_data: await readFileAsDataUrl(installer),
      release_notes: el.updateReleaseNotesInput.value.trim(),
      mandatory: Boolean(el.updateMandatoryInput.checked),
    });
    state.updateInfo.latest = result.latest || state.updateInfo.latest;
    state.updateInfo.history = result.history || state.updateInfo.history;
    el.publishUpdateForm.reset();
    renderUpdateCenter();
    showToast("Desktop update published.");
  } catch (error) {
    showToast(error.message, true);
  }
});

[el.newNationButton, el.catalogNewNationButton].forEach((button) => button.addEventListener("click", () => openEntityModal("nation")));
[el.newCompetitionButton, el.catalogNewCompetitionButton].forEach((button) => button.addEventListener("click", () => openEntityModal("competition")));
[el.newClubButton, el.catalogNewClubButton].forEach((button) => button.addEventListener("click", () => openEntityModal("club")));
el.closeEntityModalButton.addEventListener("click", () => setModalVisibility(el.entityModal, false));
el.entityNationSelect.addEventListener("change", populateEntitySelectors);
el.entityCompetitionParticipantSelect?.addEventListener("change", () => {
  const showClubAssignments = el.entityCompetitionParticipantSelect.value !== "nations";
  el.entityCompetitionClubAssignmentsField.classList.toggle("hidden", !showClubAssignments);
});

el.entityForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const type = el.entityTypeInput.value;
  const name = el.entityNameInput.value.trim();
  if (!name) return showToast("Name is required.", true);
  if (type === "competition" && !el.entityNationSelect.value) return showToast("Select a valid nation first.", true);
  try {
    const logoUrl = (await uploadSelectedLogo(type, name)) || el.entityLogoPreview.dataset.logoUrl || "";
    if (type === "nation") {
      const result = await window.desktopApi.saveNation(compactPayload({
        id: el.entityIdInput.value || "",
        name,
        logo_url: logoUrl,
      }));
      upsertCatalogStateItem("nation", result?.item);
    }
    if (type === "competition") {
      const result = await window.desktopApi.saveCompetition(compactPayload({
        id: el.entityIdInput.value || "",
        name,
        nation_id: el.entityNationSelect.value,
        type: el.entityCompetitionTypeSelect.value,
        participant_type: (el.entityCompetitionParticipantSelect.value || "club") === "nations" ? "nation" : "club",
        club_ids: selectedCompetitionClubIds(),
        logo_url: logoUrl,
      }));
      upsertCatalogStateItem("competition", result?.item);
    }
    if (type === "club") {
      const result = await window.desktopApi.saveClub(compactPayload({
        id: el.entityIdInput.value || "",
        name,
        nation_id: el.entityNationSelect.value || "",
        logo_url: logoUrl,
      }));
      upsertCatalogStateItem("club", result?.item);
    }
    setModalVisibility(el.entityModal, false);
    await refreshMetadata();
    showToast("Metadata saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.deleteEntityButton.addEventListener("click", async () => {
  const id = el.deleteEntityButton.dataset.id;
  const type = el.deleteEntityButton.dataset.type;
  if (!id || !type) return;
  try {
    if (type === "nation") await window.desktopApi.deleteNation(id);
    if (type === "competition") await window.desktopApi.deleteCompetition(id);
    if (type === "club") await window.desktopApi.deleteClub(id);
    removeCatalogStateItem(type, id);
    setModalVisibility(el.entityModal, false);
    await refreshMetadata();
    showToast("Metadata deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
});

el.approveNationSelect.addEventListener("change", () => syncApproveSelections());
el.approveCompetitionSelect.addEventListener("change", () => syncApproveSelections());
el.approveHomeClubSelect.addEventListener("change", updateApprovalPreview);
el.approveAwayClubSelect.addEventListener("change", updateApprovalPreview);
el.approveForm.addEventListener("submit", (event) => { event.preventDefault(); submitApproval(); });
el.approveChannelButton.addEventListener("click", submitApproval);
el.videoPreview?.addEventListener("error", () => {
  el.previewOverlay.textContent = "Preview playback failed for this stream.";
  el.previewOverlay.classList.remove("hidden");
});
el.removeApprovedButton.addEventListener("click", async () => {
  const approval = approvedMap().get(String(state.selectedChannel?.id || state.selectedChannel?.stream_id));
  if (!approval) return;
  try {
    await window.desktopApi.removeApprovedStream(approval.stream_id);
    await refreshApprovedMatches();
    renderChannels();
    renderPreview();
    showToast("Match mapping removed.");
  } catch (error) {
    showToast(error.message, true);
  }
});

window.desktopApi.onMenuAction(handleMenuAction);
window.desktopApi.onUpdateState((payload) => {
  if (payload?.status !== "available") {
    state.updateInfo.dismissed = false;
  }
  state.updateInfo.state = payload || state.updateInfo.state;
  renderUpdateCenter();
});
window.desktopApi.onMasterLiveState((payload) => {
  state.masterLive = payload || state.masterLive;
  renderMasterLive();
});
bootstrap().catch((error) => showToast(error.message, true));
dashboardPollIntervalId = setInterval(() => {
  if (dashboardPollInFlight) {
    return;
  }
  dashboardPollInFlight = true;
  Promise.resolve(refreshVisibleSectionData())
    .catch(() => {})
    .finally(() => {
      dashboardPollInFlight = false;
    });
}, 30000);
