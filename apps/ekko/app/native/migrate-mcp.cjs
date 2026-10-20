// Migrate only the current/default Hermes profile; preserve YAML and permissions.
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');
const requireApp = createRequire(path.resolve(process.env.TRIM_APPDEST, 'server/lib/node_modules/ekko-studio/package.json'));
const YAML = requireApp('yaml');
const home = process.env.TRIM_DATA_SHARE_PATHS.split(':')[0];
const config = path.join(process.env.HERMES_HOME || path.join(home, '.hermes'), 'config.yaml');
if (!fs.existsSync(config)) process.exit(0);
const text = fs.readFileSync(config, 'utf8');
const doc = YAML.parseDocument(text);
if (doc.errors.length) throw Error('MCP migration: invalid YAML, no changes made');
const servers = doc.get('mcp_servers');
let changed = 0;
if (YAML.isMap(servers)) for (const item of servers.items) {
  const name = String(item.key);
  const entry = item.value;
  if (!name.startsWith('ekko-studio-') || !YAML.isMap(entry)) continue;
  const args = entry.get('args');
  if (!YAML.isSeq(args)) continue;
  const old = args.items[0]?.value;
  // Restrict to this application's known legacy MCP script, never custom servers.
  if (typeof old !== 'string' || !/^\/(?:vol\d+\/@appcenter|var\/apps)\/Ekko\/(?:target\/)?server\/lib\/node_modules\/hermes-web-ui\/bin\/ekko-studio-mcp\.mjs$/.test(old)) continue;
  args.set(0, path.join(process.env.TRIM_APPDEST, 'server/lib/node_modules/ekko-studio/bin/ekko-studio-mcp.mjs'));
  entry.set('command', path.join(process.env.TRIM_APPDEST, 'node/bin/node'));
  changed++;
}
if (changed) {
  const mode = fs.statSync(config).mode & 0o777;
  const backup = config + '.before-ekko-path-migration-' + Date.now();
  fs.copyFileSync(config, backup, fs.constants.COPYFILE_EXCL);
  fs.chmodSync(backup, mode);
  if (!fs.readFileSync(backup).equals(Buffer.from(text))) throw Error('Backup mismatch');
  const tmp = config + '.ekko-migration-' + process.pid;
  fs.writeFileSync(tmp, String(doc), {mode, flag:'wx'});
  fs.renameSync(tmp, config);
}
console.log('MCP legacy paths migrated:', changed);
