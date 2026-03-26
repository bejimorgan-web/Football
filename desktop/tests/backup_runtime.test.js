const assert = require("assert");
const path = require("path");

const {
  defaultBackupSettings,
  isLocalBackendUrl,
  parseBackendUrl,
  resolveBundledPythonCandidates,
  shouldRunScheduledBackup,
} = require("../src/backup_runtime");

const defaults = defaultBackupSettings("C:\\demo", false);
assert.strictEqual(defaults.backupSchedule, "disabled");
assert.ok(defaults.backupPath.endsWith(path.join("desktop", "backups")));

const candidates = resolveBundledPythonCandidates("C:\\app", "C:\\userData", "win32");
assert.ok(candidates.some((item) => item.endsWith(path.join("runtime", "python", "python.exe"))));
assert.ok(candidates.some((item) => item.endsWith(path.join("runtime", "python", "windows", "python.exe"))));
assert.ok(candidates.some((item) => item.endsWith(path.join("backend", ".venv", "Scripts", "python.exe"))));

const macCandidates = resolveBundledPythonCandidates("/Applications/App", "/Users/demo/Library", "darwin");
assert.ok(macCandidates.some((item) => item.endsWith(path.join("runtime", "python", "macos", "bin", "python3"))));

assert.strictEqual(isLocalBackendUrl("http://127.0.0.1:8000"), true);
assert.strictEqual(isLocalBackendUrl("http://localhost:8000"), true);
assert.strictEqual(isLocalBackendUrl("https://api.example.com"), false);
assert.strictEqual(parseBackendUrl("not-a-url").hostname, "127.0.0.1");

assert.strictEqual(shouldRunScheduledBackup("daily", "", new Date("2026-03-23T10:00:00Z")), true);
assert.strictEqual(shouldRunScheduledBackup("daily", "2026-03-23T01:00:00Z", new Date("2026-03-23T10:00:00Z")), false);
assert.strictEqual(shouldRunScheduledBackup("daily", "2026-03-22T08:00:00Z", new Date("2026-03-23T10:00:00Z")), true);
assert.strictEqual(shouldRunScheduledBackup("weekly", "2026-03-20T08:00:00Z", new Date("2026-03-23T10:00:00Z")), false);
assert.strictEqual(shouldRunScheduledBackup("weekly", "2026-03-10T08:00:00Z", new Date("2026-03-23T10:00:00Z")), true);
assert.strictEqual(shouldRunScheduledBackup("monthly", "2026-02-28T23:00:00Z", new Date("2026-03-01T00:00:00Z")), true);

console.log("backup_runtime tests passed");
