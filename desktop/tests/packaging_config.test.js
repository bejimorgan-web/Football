const assert = require("assert");
const fs = require("fs");
const path = require("path");

const packageJson = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"),
);

assert.ok(packageJson.scripts.package, "package script should exist");
assert.ok(packageJson.scripts.make, "make script should exist");
assert.ok(packageJson.scripts["make:win"], "Windows make script should exist");
assert.ok(packageJson.scripts["make:mac"], "macOS make script should exist");
assert.ok(packageJson.scripts["make:linux"], "Linux make script should exist");
assert.ok(packageJson.devDependencies["electron-builder"], "electron-builder should be configured");

const extraResources = packageJson.build && packageJson.build.extraResources;
assert.ok(Array.isArray(extraResources), "extraResources should be configured");
assert.ok(extraResources.some((entry) => entry.from === "runtime"), "runtime resources should be bundled");
assert.ok(extraResources.some((entry) => entry.from === "../backend"), "backend resources should be bundled");
assert.strictEqual(packageJson.build.win.icon, "build/icons/app-icon.ico", "desktop icon should be configured");
assert.strictEqual(packageJson.build.nsis.allowToChangeInstallationDirectory, true, "NSIS directory chooser should be enabled");
assert.strictEqual(packageJson.build.nsis.displayLanguageSelector, true, "NSIS language selector should be enabled");
assert.strictEqual(packageJson.build.nsis.license, "build/licenses/license.txt", "NSIS license file should be configured");
assert.strictEqual(packageJson.build.nsis.installerIcon, "build/icons/installer-icon.ico", "installer icon should be configured");
assert.strictEqual(packageJson.build.nsis.installerHeaderIcon, "build/icons/installer-header-icon.ico", "installer header icon should be configured");

console.log("packaging_config tests passed");
