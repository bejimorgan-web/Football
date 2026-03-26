const fs = require("fs");
const path = require("path");

function defaultBackupSettings(basePath, isPackaged = false) {
  return {
    backupPath: isPackaged ? path.join(basePath, "backups") : path.join(basePath, "desktop", "backups"),
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

function resolveBundledPythonCandidates(appRoot, userDataPath = "", platform = process.platform) {
  const candidates = [];
  const runtimeRoots = [];
  if (userDataPath) {
    runtimeRoots.push(path.join(userDataPath, "python"));
  }
  runtimeRoots.push(path.join(appRoot, "runtime", "python"));

  for (const runtimeRoot of runtimeRoots) {
    if (platform === "win32") {
      candidates.push(
        path.join(runtimeRoot, "windows", "python.exe"),
        path.join(runtimeRoot, "python.exe"),
        path.join(runtimeRoot, "Scripts", "python.exe"),
      );
      continue;
    }

    const platformFolder = platform === "darwin" ? "macos" : "linux";
    candidates.push(
      path.join(runtimeRoot, platformFolder, "bin", "python3"),
      path.join(runtimeRoot, platformFolder, "bin", "python"),
      path.join(runtimeRoot, "bin", "python3"),
      path.join(runtimeRoot, "bin", "python"),
    );
  }

  if (platform === "win32") {
    candidates.push(path.join(appRoot, "..", "backend", ".venv", "Scripts", "python.exe"));
  } else {
    candidates.push(
      path.join(appRoot, "..", "backend", ".venv", "bin", "python3"),
      path.join(appRoot, "..", "backend", ".venv", "bin", "python"),
    );
  }
  return [...new Set(candidates)];
}

function resolvePythonExecutable(appRoot, userDataPath = "", platform = process.platform) {
  const candidates = resolveBundledPythonCandidates(appRoot, userDataPath, platform);
  const executable = candidates.find((candidate) => fs.existsSync(candidate));
  return {
    executable: executable || "",
    candidates,
    available: Boolean(executable),
  };
}

function parseBackendUrl(rawUrl) {
  const normalized = String(rawUrl || "http://127.0.0.1:8000").trim() || "http://127.0.0.1:8000";
  try {
    return new URL(normalized);
  } catch (_) {
    return new URL("http://127.0.0.1:8000");
  }
}

function isLocalBackendUrl(rawUrl) {
  const url = parseBackendUrl(rawUrl);
  return ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
}

function shouldRunScheduledBackup(schedule, lastRunAt, now = new Date()) {
  const normalizedSchedule = String(schedule || "disabled").trim().toLowerCase();
  if (!["daily", "weekly", "monthly"].includes(normalizedSchedule)) {
    return false;
  }

  if (!lastRunAt) {
    return true;
  }

  const previous = new Date(lastRunAt);
  if (Number.isNaN(previous.getTime())) {
    return true;
  }

  if (normalizedSchedule === "daily") {
    return now.getTime() - previous.getTime() >= 24 * 60 * 60 * 1000;
  }
  if (normalizedSchedule === "weekly") {
    return now.getTime() - previous.getTime() >= 7 * 24 * 60 * 60 * 1000;
  }
  return (
    now.getUTCFullYear() !== previous.getUTCFullYear()
    || now.getUTCMonth() !== previous.getUTCMonth()
  );
}

module.exports = {
  defaultBackupSettings,
  isLocalBackendUrl,
  parseBackendUrl,
  resolveBundledPythonCandidates,
  resolvePythonExecutable,
  shouldRunScheduledBackup,
};
