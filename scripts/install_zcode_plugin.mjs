// Installs a Claude-Code-style plugin into ZCode's plugin cache, replicating
// what the client's Settings -> Plugin Management flow does.
//
// ZCode's layout (verified against zcode.cjs):
//   <pluginsRoot>/known_marketplaces.json            marketplace registry
//   <pluginsRoot>/marketplaces/<id>/marketplace.json cached marketplace manifest
//   <pluginsRoot>/cache/<id>/<plugin>/<version>/      the plugin files
//   <pluginsRoot>/installed_plugins.json              install records
//   <pluginsRoot>/data/<plugin>@<id>/                 the plugin's data dir
//
// Usage: node install_zcode_plugin.mjs <repo> <marketplaceId> <pluginName>
import { execFileSync } from "node:child_process";
import {
  cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const PLUGINS_ROOT = join(process.env.USERPROFILE, ".zcode", "cli", "plugins");
const MARKETPLACES_FILE = join(PLUGINS_ROOT, "known_marketplaces.json");
const INSTALLED_FILE = join(PLUGINS_ROOT, "installed_plugins.json");

const [repo, marketplaceId, pluginName] = process.argv.slice(2);
if (!repo || !marketplaceId || !pluginName) {
  console.error("usage: install_zcode_plugin.mjs <owner/repo> <marketplaceId> <pluginName>");
  process.exit(1);
}

const readJson = (p) => {
  try {
    return JSON.parse(readFileSync(p, "utf8"));
  } catch {
    return undefined;
  }
};
const writeJson = (p, value) => {
  mkdirSync(join(p, ".."), { recursive: true });
  writeFileSync(p, `${JSON.stringify(value, null, 2)}\n`, "utf8");
};

// 1. Clone the repository.
const tmp = mkdtempSync(join(tmpdir(), "zcode-plugin-src-"));
execFileSync("git", ["clone", "--depth", "1", `https://github.com/${repo}.git`, tmp], {
  stdio: "ignore",
});

// 2. Locate the marketplace manifest and the plugin manifest.
const marketplaceManifestPath = join(tmp, ".claude-plugin", "marketplace.json");
if (!existsSync(marketplaceManifestPath)) {
  throw new Error(`no .claude-plugin/marketplace.json in ${repo}`);
}
const marketplace = JSON.parse(readFileSync(marketplaceManifestPath, "utf8"));
const entry = marketplace.plugins.find((p) => p.name === pluginName);
if (!entry) throw new Error(`marketplace has no plugin named ${pluginName}`);

const pluginRoot = resolve(tmp, entry.source ?? "./");
const pluginManifestPath = join(pluginRoot, ".claude-plugin", "plugin.json");
if (!existsSync(pluginManifestPath)) {
  throw new Error(`no .claude-plugin/plugin.json under ${entry.source ?? "./"}`);
}
const pluginManifest = JSON.parse(readFileSync(pluginManifestPath, "utf8"));
if (pluginManifest.name !== pluginName) {
  throw new Error(`plugin manifest name ${pluginManifest.name} != ${pluginName}`);
}
const version = pluginManifest.version ?? "0.0.0";
const now = new Date().toISOString();

// 3. Materialize the plugin into the cache.
const installPath = join(PLUGINS_ROOT, "cache", marketplaceId, pluginName, version);
rmSync(installPath, { recursive: true, force: true });
mkdirSync(installPath, { recursive: true });
cpSync(pluginRoot, installPath, { recursive: true });

// 4. Cache the marketplace manifest.
writeJson(join(PLUGINS_ROOT, "marketplaces", marketplaceId, "marketplace.json"), marketplace);

// 5. Register the marketplace.
const known = readJson(MARKETPLACES_FILE) ?? { version: 1, marketplaces: [] };
known.version ??= 1;
known.marketplaces = (known.marketplaces ?? []).filter((m) => m.id !== marketplaceId);
known.marketplaces.push({
  id: marketplaceId,
  source: { source: "github", repo },
  name: marketplaceId,
  description: marketplace.description ?? "",
  addedAt: now,
  pluginCount: marketplace.plugins?.length ?? 0,
  lastUpdated: now,
});
writeJson(MARKETPLACES_FILE, known);

// 6. Record the install.
const installed = readJson(INSTALLED_FILE) ?? { version: 1, plugins: [] };
installed.version ??= 1;
installed.plugins = (installed.plugins ?? []).filter((p) => p.id !== `${pluginName}@${marketplaceId}`);
installed.plugins.push({
  id: `${pluginName}@${marketplaceId}`,
  name: pluginName,
  marketplace: marketplaceId,
  version,
  installPath,
  installedAt: now,
  scope: "user",
});
writeJson(INSTALLED_FILE, installed);

// 7. The plugin's data directory.
mkdirSync(join(PLUGINS_ROOT, "data", `${pluginName}@${marketplaceId}`), { recursive: true });

rmSync(tmp, { recursive: true, force: true });
console.log(`installed ${pluginName}@${marketplaceId} ${version}`);
console.log(`  installPath: ${installPath}`);
