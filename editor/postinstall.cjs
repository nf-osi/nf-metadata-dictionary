// node-pty ships prebuilt `spawn-helper` binaries that sometimes lose their
// execute bit during npm extraction, which makes pty.spawn fail with
// "posix_spawnp failed". Restore +x on every install.
const fs = require('fs');
const base = 'node_modules/node-pty/prebuilds';
try {
  for (const arch of fs.readdirSync(base)) {
    const helper = `${base}/${arch}/spawn-helper`;
    if (fs.existsSync(helper)) {
      try { fs.chmodSync(helper, 0o755); } catch (e) { /* ignore */ }
    }
  }
} catch (e) { /* node-pty not installed; nothing to do */ }
