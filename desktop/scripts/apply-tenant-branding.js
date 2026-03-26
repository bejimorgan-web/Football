const fs = require("fs");
const path = require("path");

async function copyIfExists(source, target) {
  if (!fs.existsSync(source)) {
    return false;
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
  return true;
}

exports.default = async function applyTenantBranding() {
  const tenantId = String(process.env.TENANT_BRANDING_ID || process.env.TENANT_ID || "default").trim() || "default";
  const brandingDir = path.resolve(__dirname, "..", "..", "backend", "storage", "branding", tenantId);
  const buildIconsDir = path.resolve(__dirname, "..", "build", "icons");

  const desktopIcon = path.join(brandingDir, "desktop_icon.ico");
  const favicon = path.join(brandingDir, "favicon.ico");

  const appliedDesktopIcon = await copyIfExists(desktopIcon, path.join(buildIconsDir, "app-icon.ico"));
  await copyIfExists(desktopIcon, path.join(buildIconsDir, "installer-icon.ico"));
  await copyIfExists(desktopIcon, path.join(buildIconsDir, "installer-header-icon.ico"));

  if (!appliedDesktopIcon && fs.existsSync(favicon)) {
    await copyIfExists(favicon, path.join(buildIconsDir, "app-icon.ico"));
    await copyIfExists(favicon, path.join(buildIconsDir, "installer-icon.ico"));
    await copyIfExists(favicon, path.join(buildIconsDir, "installer-header-icon.ico"));
  }
};
