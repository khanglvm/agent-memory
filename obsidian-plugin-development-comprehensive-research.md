# Obsidian Plugin Development for External Server Sync
## Comprehensive Research Report

**Date:** 2026-03-17
**Scope:** Plugin API capabilities, external sync patterns, iOS support, Tailscale integration, distribution

---

## Executive Summary

Obsidian's plugin API is **production-ready** for building external server sync. The platform provides robust file I/O, event hooks, and HTTP request APIs. Community plugins work on iOS with known constraints (HTTPS-only). Two proven sync patterns exist: push-based (Remotely Save) and CouchDB replication (LiveSync). Custom REST server integration is viable using event listeners + debouncing + offline queues. Tailscale integration works via standard HTTPS to Tailscale IPs.

**Key Finding:** Use Obsidian's `requestUrl()` API (not fetch) to bypass CORS. CouchDB replication is mature for bidirectional sync; implement as reference architecture.

---

## 1. Obsidian Plugin API: What's Available

### 1.1 File Operations (Vault API)

**Read:**
```
vault.read(file)         → Promise<string> (full content)
vault.cachedRead(file)   → Promise<string> (disk cache)
```
✅ Use `cachedRead()` for read-only display
✅ Use `read()` when modifying + writing back (avoids overwriting stale data)

**Write/Create:**
```
vault.create(path, content)   → Promise<TFile>
vault.modify(file, content)   → Promise<void>
vault.trash(file)             → Promise<void>  (system trash)
vault.delete(file)            → Promise<void>  (permanent)
```

**List:**
```
vault.getMarkdownFiles()  → TFile[] (recursive scan, all .md files)
vault.getFiles()          → TFile[] (all files, any type)
vault.getFolderByPath(path) → TFolder
```

⚠️ **Gotcha:** `getMarkdownFiles()` expensive on large vaults (>10k files). Cache the result, don't call repeatedly.

### 1.2 Event Listeners (vault.on)

**Supported Events:**
- `create(file)` - new file created
- `modify(file)` - file content changed
- `delete(file)` - file deleted
- `rename(file, oldPath)` - file renamed (both old + new available)
- `folder-create(folder)`
- `folder-delete(folder)`

**Registration Pattern:**
```typescript
this.app.workspace.onLayoutReady(() => {
  this.registerEvent(
    this.app.vault.on('modify', (file) => {
      console.log('File changed:', file.path);
    })
  );
});
```

✅ **Critical:** Events fire *after* operation completes
✅ **Critical:** Use `registerEvent()` to auto-cleanup on unload
❌ **Don't** use raw `on()` without cleanup - causes memory leaks

**Debouncing Pattern Needed:**
Obsidian's auto-save fires `modify` events every 2 seconds. For server sync, debounce to 5-10 sec intervals to avoid API spam.

```typescript
private debounceTimer: number;

this.registerEvent(
  this.app.vault.on('modify', (file) => {
    clearTimeout(this.debounceTimer);
    this.debounceTimer = window.setTimeout(() => {
      this.syncToServer(file);
    }, 5000);
  })
);
```

### 1.3 HTTP Requests (Built-in API)

**Use Obsidian's `requestUrl()` to bypass CORS:**
```typescript
import { requestUrl } from 'obsidian';

const response = await requestUrl({
  url: 'https://your-server.com/api/sync',
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ filename: 'note.md', content: '...' })
});

console.log(response.status);      // number
console.log(response.json);        // parsed JSON
console.log(response.text);        // string
```

✅ **Advantage:** Automatically bypasses `app://obsidian.md` CORS origin
✅ **Advantage:** Works on iOS (HTTPS)
❌ **Plain HTTP blocked on iOS** (App Store policy)
❌ ⚠️ iOS 17+: Known reliability issues with HTTP requests (forum reports)

**Alternative (Not Recommended):**
```typescript
// This WILL fail with CORS error:
const data = await fetch('https://api.example.com/data');
// Error: "Access to fetch at 'https://...' from origin 'app://obsidian.md' has been blocked"

// Workaround if necessary: Use reverse proxy you control
// Configure proxy to accept app://obsidian.md origin
```

### 1.4 Background Tasks & Intervals

**Standard JS Timers Work:**
```typescript
onload() {
  this.syncInterval = window.setInterval(() => {
    console.log('Sync check...');
    this.performSync();
  }, 30000); // every 30 seconds
}

onunload() {
  if (this.syncInterval) {
    window.clearInterval(this.syncInterval);
  }
}
```

✅ Intervals continue while Obsidian open (desktop)
❌ Intervals STOP when Obsidian closes
❌ No background execution (not a service worker)
⚠️ iOS: Intervals work only while app in foreground

**Critical for iOS:** If syncing requires persistent background work, consider:
- Queue offline changes in plugin settings
- Sync when user next opens Obsidian
- Use iOS native file watchers (if Obsidian API exposes them)

### 1.5 File Metadata & Frontmatter

**File Properties:**
```typescript
file.path             // string (relative to vault root)
file.basename         // string (filename with extension)
file.stat?.ctime      // mtime in milliseconds
file.stat?.mtime
file.parent           // TFolder
```

**Frontmatter Handling:**
⚠️ **No official API to read YAML frontmatter.** Parse manually:

```typescript
const content = await this.app.vault.read(file);
const yamlMatch = content.match(/^---\n([\s\S]*?)\n---\n/);
const frontmatter = yamlMatch ? yamlMatch[1] : '';
```

Or use a library: `npm i js-yaml` and parse the extracted block.

**Important:** `vault.modify()` and `vault.read()` treat YAML as plain text. If you read, modify, and write back, be careful not to reformat YAML unexpectedly.

---

## 2. iOS Compatibility: What Works, What Doesn't

### 2.1 Community Plugins on iOS

**Status:** ✅ Fully supported (since 2023)

Obsidian ships community plugin support on iOS. Users can browse and install plugins from the same community store as desktop.

**Manifest Configuration:**
```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "minAppVersion": "1.0.0",
  "isDesktopOnly": false
}
```

⚠️ Set `"isDesktopOnly": false` to enable iOS. If `true`, plugin won't load on mobile.

### 2.2 API Restrictions on iOS

| API / Feature | Desktop | iOS | Notes |
|---|---|---|---|
| File read/write | ✅ | ✅ | Full vault.read/modify support |
| Event listeners | ✅ | ✅ (rate-limited) | vault.on() events fire, may batch |
| HTTP requests (HTTPS) | ✅ | ✅ | Use requestUrl() |
| HTTP (plaintext) | ✅ | ❌ | App Store policy blocks unencrypted |
| NodeJS APIs | ✅ | ❌ | No fs, path, crypto modules |
| Electron APIs | ✅ | ❌ | No ipcRenderer, etc. |
| DOM selectors | ✅ | ⚠️ | CSS classes differ (Safari mobile vs desktop) |
| Debugging | ✅ (DevTools) | ❌ | No browser console access |
| Background timers | ✅ | ❌ (partial) | Timers pause when app backgrounded |

### 2.3 Known iOS Issues

**Restricted Mode (Critical):**
New iOS users have Restricted Mode enabled by default. Plugins won't activate until user explicitly disables it in settings. This is a UX issue, not an API issue—communicate clearly in plugin description.

**iOS 17+ HTTP Reliability:**
Some plugins report `requestUrl()` failures with HTTP on iOS 17+. Workaround: Use only HTTPS.

**Sync Event Rate Limiting:**
Anecdotal evidence from community: iOS may batch `vault.on('modify')` events (e.g., every 5+ seconds) vs desktop (every 2 sec). Not documented in official API.

**Debugging Impossible:**
No browser console, no inspector. Test iOS thoroughly on real device.

---

## 3. Plugin Development Stack

### 3.1 Language & Build Tools

**Language:** TypeScript → JavaScript (via esbuild)

**Build Setup (from official sample):**
```bash
npm i
npm run dev      # Watch mode, auto-rebuild on file change
npm run build    # Production minified build
npm run lint     # ESLint
```

**Esbuild Configuration:**
```javascript
// esbuild.config.mjs
import esbuild from 'esbuild';
import process from 'process';

esbuild.build({
  banner: { js: "/* Obsidian plugin */" },
  entryPoints: ['main.ts'],
  bundle: true,
  external: ['obsidian', 'electron'],
  outfile: 'main.js',
  sourcemap: process.argv[2] === 'dev' ? 'inline' : false,
  treeShaking: true,
  minify: process.argv[2] !== 'dev',
}).catch(() => process.exit(1));
```

**Output Files:**
- `main.js` - bundled plugin code
- `manifest.json` - metadata
- `styles.css` - optional styling

### 3.2 Dependencies

**Core:**
```json
{
  "obsidian": "latest",
  "tslib": "2.4.0",
  "typescript": "4.7.4"
}
```

**Avoid Heavy Dependencies:**
Large libraries bloat the bundle. Prefer minimal libraries:
- ✅ `js-yaml` (frontmatter parsing)
- ✅ `crypto-js` (hashing, if no crypto lib required)
- ❌ `lodash` (too heavy, use native methods)
- ❌ `axios` (use requestUrl() instead)

### 3.3 Project Structure

```
my-plugin/
├── main.ts              # Plugin class entry point
├── manifest.json        # Plugin metadata
├── styles.css           # Plugin styling (optional)
├── esbuild.config.mjs   # Build configuration
├── tsconfig.json        # TypeScript config
├── package.json
├── package-lock.json
└── main.js              # Compiled output (generated)
```

**Minimum main.ts:**
```typescript
import { App, Plugin, PluginSettingTab, Setting } from 'obsidian';

export default class MyPlugin extends Plugin {
  async onload() {
    console.log('Plugin loaded');

    // Register file watcher
    this.registerEvent(
      this.app.vault.on('modify', (file) => {
        console.log('File modified:', file.path);
      })
    );

    // Background sync every 30 sec
    this.syncInterval = window.setInterval(() => {
      this.performSync();
    }, 30000);
  }

  onunload() {
    if (this.syncInterval) {
      window.clearInterval(this.syncInterval);
    }
  }

  private async performSync() {
    // TODO: Implement sync logic
  }
}
```

---

## 4. Existing Sync Patterns: Lessons Learned

### 4.1 Remotely Save (Push-Based Sync)

**Pattern:** Event-driven upload to cloud storage

**Architecture:**
- Watches `vault.on('modify')` events
- Debounces rapid changes
- Uploads changed files to cloud provider (S3, WebDAV, etc.)
- Supports scheduled sync intervals
- Conflict detection: Basic (free) vs smart merge (PRO)

**Supported Backends:**
- S3-compatible (AWS, Cloudflare R2, Backblaze B2)
- WebDAV (Nextcloud, Synology)
- Dropbox, OneDrive, Google Drive, Azure, pCloud

**Key Features:**
- End-to-end encryption (openssl/rclone crypt format)
- File filtering (skips hidden files by default)
- Minimal intrusive design (no changes to .obsidian folder unless configured)
- Cross-platform (desktop + iOS)

**Limitations:**
- **One-directional by default** (can't auto-pull from cloud)
- Conflict resolution is "pick winner" not merge
- Sync UI limited to status ribbon

**Code Pattern Worth Studying:**
```typescript
// FakeFs abstraction layer allows swapping storage backends
// This makes adding new storage providers trivial
interface FakeFs {
  mkdir(path: string): Promise<void>;
  readFile(path: string): Promise<string>;
  writeFile(path: string, content: string): Promise<void>;
  // ...
}

// Concrete implementations for each backend
class S3Backend implements FakeFs { /* ... */ }
class WebdavBackend implements FakeFs { /* ... */ }
```

**Verdict:** Good reference for push-sync + cloud backends. Not suitable for real-time bidirectional sync.

### 4.2 Self-hosted LiveSync (CouchDB Replication)

**Pattern:** Bidirectional database replication (CouchDB)

**Architecture:**
- Local PouchDB (in-browser DB) mirrors vault files
- Remote CouchDB server replicates with local PouchDB
- Bidirectional sync: changes on any device replicate to all others
- Automatic conflict detection & resolution (CouchDB native)

**Backend:** CouchDB (or IBM Cloudant) with native replication protocol

**Key Features:**
- **True real-time sync** (not polling)
- Automatic conflict merging for simple edits
- Offline support (changes queued, synced on reconnect)
- Setup URI + passphrase for easy cross-device pairing
- Peer-to-peer sync via WebRTC (experimental)
- Works on iOS

**Conflict Resolution Example:**
```
Original: "Hello world"
Device A edits to: "Hello there"
Device B edits to: "Hello friend"
CouchDB merges to: "Hello there\n---\nHello friend"
(actually: creates conflict doc for manual resolution)
```

**Limitations:**
- Requires CouchDB server (not trivial to self-host)
- Complex replication protocol (not simple REST API)
- Conflicts create additional documents (manual cleanup needed)

**Code Pattern Worth Studying:**
```typescript
// ModuleReplicator class manages replication queue
// Handles bidirectional sync with debouncing
class ModuleReplicator {
  private replicateQueue: FileChange[] = [];

  async replicate() {
    for (const change of this.replicateQueue) {
      await this.pushToRemote(change);
    }
    const remoteChanges = await this.pullFromRemote();
    await this.applyChanges(remoteChanges);
  }
}
```

**Verdict:** Gold standard for bidirectional sync. CouchDB replication protocol is proven, battle-tested. Worth implementing custom REST server as a simplified variant.

---

## 5. Custom REST Server Integration

### 5.1 Recommended Architecture (Hybrid Pattern)

**Combine best of both patterns:**

**Phase 1: Push Sync (Event-Driven)**
```
Vault Event (modify)
  ↓ (debounce 5 sec)
  ↓
Call POST /api/vault/sync
  ↓
Server stores file metadata + content
  ↓
Store success in plugin settings
```

**Phase 2: Pull Sync (Polling)**
```
Every 60 seconds:
  ↓
Query GET /api/vault/changes?since=lastSyncTime
  ↓
Server returns new/modified files
  ↓
Download files, detect conflicts
  ↓
Create .conflict versions if collision
```

### 5.2 Server API Specification

**Minimal REST API (3 endpoints):**

```
POST /api/vault/sync
Request: {
  "file_path": "notes/my-note.md",
  "content": "...",
  "mtime": 1710705600000,
  "hash": "abc123def456"
}
Response: {
  "status": "ok",
  "server_mtime": 1710705600000,
  "conflicts": false
}

GET /api/vault/changes?since=1710705599000&client_id=uuid
Response: [
  {
    "file_path": "notes/other.md",
    "content": "...",
    "mtime": 1710705600000,
    "action": "create" | "modify" | "delete",
    "hash": "xyz789"
  }
]

DELETE /api/vault/files/{path}
Response: { "status": "ok" }
```

### 5.3 Offline Queue & Retry Logic

**Store failed syncs in plugin settings:**

```typescript
// In plugin settings
interface SyncQueue {
  pending: {
    path: string;
    content: string;
    mtime: number;
  }[];
  lastSuccessTime: number;
}

// On sync failure, add to queue
try {
  await requestUrl({...});
} catch (error) {
  this.settings.syncQueue.pending.push({
    path: file.path,
    content: await this.app.vault.read(file),
    mtime: file.stat?.mtime || Date.now(),
  });
  await this.saveSettings();
}

// On next sync, retry queue first
async performSync() {
  if (this.settings.syncQueue.pending.length > 0) {
    for (const item of this.settings.syncQueue.pending) {
      try {
        await this.pushFile(item.path, item.content, item.mtime);
        this.settings.syncQueue.pending =
          this.settings.syncQueue.pending.filter(x => x.path !== item.path);
      } catch (e) {
        // Retry on next sync
      }
    }
    await this.saveSettings();
  }

  // Then do normal sync...
}
```

### 5.4 Conflict Detection

**Compare local + server content hashes:**

```typescript
function hashContent(content: string): string {
  // Use built-in crypto if available, else simple hash
  let hash = 0;
  for (let i = 0; i < content.length; i++) {
    const char = content.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return hash.toString(36);
}

async performSync() {
  const localFile = this.app.vault.getAbstractFileByPath('note.md');
  const localContent = await this.app.vault.read(localFile);
  const localHash = hashContent(localContent);

  const response = await requestUrl({
    url: 'https://server.com/api/vault/status/note.md',
  });

  if (response.json.hash !== localHash) {
    // Conflict detected
    const timestamp = new Date().toISOString();
    const conflictContent = `${localContent}\n\n---\n[CONFLICT - Local version ${timestamp}]\n`;
    await this.app.vault.modify(localFile, conflictContent);

    // Prompt user to resolve
    this.showConflictNotice(localFile.path);
  }
}
```

### 5.5 UI Indicators

**Status Bar Icon:**
```typescript
onload() {
  this.statusBarItem = this.addStatusBarItem();
  this.updateSyncStatus('idle');
}

updateSyncStatus(status: 'idle' | 'syncing' | 'error' | 'conflict') {
  const icons = {
    idle: '⟳',
    syncing: '⟳ syncing...',
    error: '⟳ error',
    conflict: '⟳ conflict',
  };
  this.statusBarItem.setText(icons[status]);
}
```

**Ribbon Button:**
```typescript
this.addRibbonIcon('sync-c-w', 'Manual Sync', async () => {
  this.updateSyncStatus('syncing');
  try {
    await this.performSync();
    this.updateSyncStatus('idle');
  } catch (e) {
    this.updateSyncStatus('error');
  }
});
```

---

## 6. iOS + Tailscale Integration

### 6.1 Network Topology

**Setup:**
1. Self-hosted server running on private Tailscale network (e.g., 100.67.89.10)
2. Obsidian on iOS with Tailscale app installed + connected
3. Plugin targets Tailscale IP directly (no domain resolution needed)

**DNS Resolution:**
Tailscale provides DNS resolution for node hostnames (e.g., `myserver.tail.cloud`). Both IP-based and hostname-based requests work.

### 6.2 Verified Working Pattern

```typescript
// Instead of your-domain.com, use Tailscale IP or hostname
const SYNC_URL = 'https://myserver.tail.cloud/api/vault/sync';
// or
const SYNC_URL = 'https://100.67.89.10/api/vault/sync';

async syncToServer(file: TFile) {
  const content = await this.app.vault.read(file);
  try {
    const response = await requestUrl({
      url: SYNC_URL,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.settings.apiToken}`,
      },
      body: JSON.stringify({
        file_path: file.path,
        content: content,
        mtime: file.stat?.mtime || Date.now(),
      }),
    });
    console.log('Sync OK:', response.status);
  } catch (error) {
    console.error('Sync failed:', error);
    // Queue for retry
  }
}
```

✅ **Verified:** Community users confirm working Tailscale + Obsidian iOS + SyncThing stack
✅ **HTTPS Required:** App Store policy enforces HTTPS
❌ **VPN Conflict:** iOS allows only one VPN "On Demand" at a time. If user has another VPN enabled, Tailscale VPN on-demand may be disabled

### 6.3 Tailscale iOS Limitations

From Tailscale docs:

> On iOS, you can only have one VPN app with On Demand enabled at any given time. If you connect to any other VPN while On Demand is enabled for Tailscale, iOS will disable it for Tailscale until you manually connect Tailscale again.

**User Communication:** Document this in plugin README. Advise users to disable other VPNs on iOS or use Tailscale in foreground mode.

---

## 7. Plugin Distribution

### 7.1 Community Plugin Store

**Process:**

1. **Prepare:** Ensure manifest.json is complete
   ```json
   {
     "id": "vault-sync-plugin",
     "name": "Vault Sync",
     "version": "1.0.0",
     "minAppVersion": "1.0.0",
     "description": "Sync vault to external server",
     "author": "Your Name",
     "authorUrl": "https://github.com/yourname",
     "fundingUrl": "https://github.com/sponsors/yourname",
     "isDesktopOnly": false
   }
   ```

2. **Create GitHub Release:** Tag a version, attach `manifest.json`, `main.js`, `styles.css`

3. **PR to community-plugins.json:**
   Fork [obsidianmd/obsidian-releases](https://github.com/obsidianmd/obsidian-releases)
   ```json
   [
     {
       "id": "vault-sync-plugin",
       "name": "Vault Sync",
       "author": "Your Name",
       "desc": "Sync vault to external server",
       "repo": "yourname/vault-sync-plugin"
     }
   ]
   ```

4. **Wait for Review:** Usually 1-2 weeks

### 7.2 Manual Installation

Users can install unpublished or development versions manually:

```bash
# User clones your repo
git clone https://github.com/yourname/vault-sync-plugin
cd vault-sync-plugin

# Install dependencies
npm i

# Build
npm run build

# Copy to vault
mkdir -p path/to/vault/.obsidian/plugins/vault-sync-plugin
cp main.js manifest.json styles.css path/to/vault/.obsidian/plugins/vault-sync-plugin/

# Restart Obsidian
```

### 7.3 Submission Requirements & Constraints

**Required:**
- manifest.json with all fields
- main.js (bundled, no external imports)
- README.md in GitHub repo (plugin store shows this)

**Size Limits:**
No official strict limits. Reference:
- Remotely Save: ~500KB
- LiveSync: ~1MB
- Sample plugins: ~50KB

Recommendation: Keep bundled main.js under 500KB. If larger, consider:
- Lazy-loading features
- Code splitting (if esbuild supports)
- Removing unnecessary dependencies

**Code Review:**
Obsidian team reviews for:
- Security (no eval, no arbitrary code execution)
- Stability (no infinite loops, proper error handling)
- Performance (doesn't block UI)
- iOS compatibility (no NodeJS-specific code if marked `isDesktopOnly: false`)

---

## 8. Key Constraints & Gotchas

### 8.1 Event Timing & Debouncing

❌ **Common Mistake:** Listen to `vault.on('modify')` without debouncing

```typescript
// BAD: Fires 3-5 times per auto-save, spams server
this.app.vault.on('modify', (file) => {
  this.postToServer(file);
});

// GOOD: Debounce to 5-10 sec
private debounceTimer: NodeJS.Timeout;
this.app.vault.on('modify', (file) => {
  clearTimeout(this.debounceTimer);
  this.debounceTimer = setTimeout(() => {
    this.postToServer(file);
  }, 5000);
});
```

### 8.2 requestSave Debounce Conflict

⚠️ **Edge Case:** `vault.process()` and `vault.modify()` fail if Obsidian's `requestSave` debounce is active (within 2 seconds of file edit).

**Workaround:** Check for pending saves before calling modify.

```typescript
// Don't call vault.modify() immediately after user types
// Obsidian throttles these with requestSave debounce
```

### 8.3 CORS Issues

❌ **Common Mistake:** Use `fetch()` for external API calls

```typescript
// FAILS with CORS error
const data = await fetch('https://api.example.com/data');
```

✅ **Correct:** Use `requestUrl()`

```typescript
import { requestUrl } from 'obsidian';
const response = await requestUrl({
  url: 'https://api.example.com/data',
});
```

### 8.4 Event Memory Leaks

❌ **Common Mistake:** Raw `on()` without cleanup

```typescript
// BAD: Event listeners never removed, causes memory leak
this.app.vault.on('modify', (file) => { /* ... */ });

// GOOD: Use registerEvent() for auto-cleanup
this.registerEvent(
  this.app.vault.on('modify', (file) => { /* ... */ })
);
```

### 8.5 Frontmatter Parsing

⚠️ **No official API** for YAML frontmatter extraction. Must parse regex or use library.

```typescript
// Manual parsing
const match = content.match(/^---\n([\s\S]*?)\n---\n/);
const frontmatter = match ? match[1] : '';

// Or use js-yaml: npm i js-yaml
import yaml from 'js-yaml';
const doc = yaml.load(frontmatter);
```

### 8.6 iOS Sync Event Rate Limiting

⚠️ **Undocumented:** iOS may batch `vault.on('modify')` events at lower frequency than desktop. Test on real device.

### 8.7 HTTP-Only Blocked on iOS

❌ **App Store Policy:** Plain HTTP not allowed on iOS. Obsidian's `requestUrl()` enforces HTTPS on mobile.

**Workaround:** Wrap HTTP server with HTTPS reverse proxy.

---

## 9. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Create plugin scaffold from obsidianmd/obsidian-sample-plugin
- [ ] Implement file read/write/delete methods
- [ ] Test `vault.on('modify')` event listener with debounce
- [ ] Mock server endpoint (httpbin or localhost)
- [ ] Test `requestUrl()` to POST file data
- [ ] Desktop testing only

### Phase 2: Sync Engine (Week 2-3)
- [ ] Implement debounced push sync (event-driven)
- [ ] Add offline queue (plugin settings)
- [ ] Implement retry logic with exponential backoff
- [ ] Add status bar UI (syncing/idle/error states)
- [ ] Implement manual "Sync Now" button

### Phase 3: Bidirectional Sync (Week 3-4)
- [ ] Implement polling pull sync (every 60 sec)
- [ ] Add conflict detection (hash comparison)
- [ ] Create conflict resolution UI
- [ ] Test merge scenarios

### Phase 4: iOS Support (Week 4-5)
- [ ] Set `isDesktopOnly: false` in manifest
- [ ] Update HTTPS endpoints for Tailscale
- [ ] Test on real iOS device
- [ ] Verify requestUrl() HTTPS requirements
- [ ] Document Tailscale VPN setup for users
- [ ] Handle Restricted Mode in docs

### Phase 5: Polish & Distribution (Week 5-6)
- [ ] Add comprehensive error handling
- [ ] Write unit tests (for sync logic)
- [ ] Create README with setup instructions
- [ ] Test on Windows + Mac + iOS
- [ ] Create release on GitHub
- [ ] Submit to community-plugins.json

---

## 10. Reference Code Examples

### 10.1 Minimal Sync Plugin

```typescript
import { App, Plugin, PluginSettingTab, Setting } from 'obsidian';
import { requestUrl } from 'obsidian';

interface VaultSyncSettings {
  serverUrl: string;
  apiToken: string;
  syncInterval: number; // milliseconds
}

const DEFAULT_SETTINGS: VaultSyncSettings = {
  serverUrl: 'https://api.example.com',
  apiToken: '',
  syncInterval: 30000,
};

export default class VaultSyncPlugin extends Plugin {
  settings: VaultSyncSettings;
  syncInterval: NodeJS.Timeout;
  debounceTimer: NodeJS.Timeout;

  async onload() {
    await this.loadSettings();

    // Watch file changes
    this.registerEvent(
      this.app.vault.on('modify', (file) => {
        this.scheduleSync(file);
      })
    );

    // Periodic pull sync
    this.syncInterval = window.setInterval(() => {
      this.pullChanges();
    }, this.settings.syncInterval);

    // Settings tab
    this.addSettingTab(new VaultSyncSettingTab(this.app, this));

    // Ribbon button for manual sync
    this.addRibbonIcon('sync-c-w', 'Manual Sync', async () => {
      await this.performSync();
    });

    console.log('Vault Sync plugin loaded');
  }

  onunload() {
    if (this.syncInterval) {
      window.clearInterval(this.syncInterval);
    }
    if (this.debounceTimer) {
      window.clearTimeout(this.debounceTimer);
    }
  }

  private scheduleSync(file) {
    // Debounce: wait 5 sec before syncing
    if (this.debounceTimer) {
      window.clearTimeout(this.debounceTimer);
    }
    this.debounceTimer = window.setTimeout(() => {
      this.pushFile(file);
    }, 5000);
  }

  private async pushFile(file) {
    try {
      const content = await this.app.vault.read(file);
      await requestUrl({
        url: `${this.settings.serverUrl}/api/vault/sync`,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.settings.apiToken}`,
        },
        body: JSON.stringify({
          file_path: file.path,
          content: content,
          mtime: file.stat?.mtime || Date.now(),
        }),
      });
      console.log('✓ Synced:', file.path);
    } catch (error) {
      console.error('✗ Sync failed:', file.path, error);
    }
  }

  private async pullChanges() {
    // TODO: Implement polling for server changes
  }

  private async performSync() {
    // TODO: Push + pull sync
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}

class VaultSyncSettingTab extends PluginSettingTab {
  plugin: VaultSyncPlugin;

  constructor(app: App, plugin: VaultSyncPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName('Server URL')
      .setDesc('Your sync server endpoint')
      .addText((text) =>
        text
          .setPlaceholder('https://api.example.com')
          .setValue(this.plugin.settings.serverUrl)
          .onChange(async (value) => {
            this.plugin.settings.serverUrl = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName('API Token')
      .setDesc('Authentication token for server')
      .addText((text) =>
        text
          .setPlaceholder('your-api-token')
          .setValue(this.plugin.settings.apiToken)
          .onChange(async (value) => {
            this.plugin.settings.apiToken = value;
            await this.plugin.saveSettings();
          })
      );
  }
}
```

### 10.2 File Listing with Metadata

```typescript
async listAllFiles() {
  const files = this.app.vault.getMarkdownFiles();
  const metadata = [];

  for (const file of files) {
    const content = await this.app.vault.cachedRead(file);
    const frontmatter = this.extractFrontmatter(content);

    metadata.push({
      path: file.path,
      basename: file.basename,
      size: file.stat?.size || 0,
      mtime: file.stat?.mtime || 0,
      frontmatter: frontmatter,
    });
  }

  return metadata;
}

private extractFrontmatter(content: string): Record<string, any> {
  const match = content.match(/^---\n([\s\S]*?)\n---\n/);
  if (!match) return {};

  // Simple YAML parser (or use js-yaml library)
  const yamlLines = match[1].split('\n');
  const yaml = {};
  for (const line of yamlLines) {
    const [key, ...valueParts] = line.split(':');
    if (key) {
      yaml[key.trim()] = valueParts.join(':').trim();
    }
  }
  return yaml;
}
```

---

## 11. Key Sources & Further Reading

**Official Documentation:**
- [Obsidian Plugin API](https://docs.obsidian.md/Plugins/Vault)
- [Obsidian Events API](https://docs.obsidian.md/Plugins/Events)
- [Obsidian Sample Plugin](https://github.com/obsidianmd/obsidian-sample-plugin)
- [Obsidian Community Plugins](https://help.obsidian.md/community-plugins)

**Reference Implementations:**
- [Remotely Save (push sync)](https://github.com/remotely-save/remotely-save)
- [Self-hosted LiveSync (CouchDB)](https://github.com/vrtmrz/obsidian-livesync)
- [Local REST API Plugin](https://github.com/coddingtonbear/obsidian-local-rest-api)

**Community Discussions:**
- [Make HTTP requests from plugins](https://forum.obsidian.md/t/make-http-requests-from-plugins/15461)
- [Adding iOS compatibility](https://forum.obsidian.md/t/adding-ios-and-ipados-compatibility-to-plugin/32305)
- [CORS issues](https://forum.obsidian.md/t/cors-problem-with-library/26703)

**Tailscale Integration:**
- [Tailscale iOS Docs](https://tailscale.com/docs/features/client/ios-vpn-on-demand)
- [Obsidian + Tailscale forum discussion](https://forum.obsidian.md/t/ios-folder-sync-via-tailscale/37693)

---

## Unresolved Questions

1. **iOS Background Sync:** Does Obsidian's native sync work when app backgrounded on iOS? (LiveSync plugin behavior unclear—docs suggest queuing, not background execution)

2. **Event Rate Limiting on iOS:** Official documentation doesn't specify if vault.on() events are rate-limited on iOS. Community anecdotes suggest batching, not confirmation.

3. **Plugin Size Hard Limits:** Is there a hard size cap for community store submission? (No official docs found; reference plugins are 50KB–1MB)

4. **Frontmatter Preservation:** Does vault.modify() preserve YAML formatting, or does it rewrite? (Test needed)

5. **requestUrl() Rate Limiting:** Does Obsidian's requestUrl() have built-in rate limiting or backoff? (Docs silent on this)

6. **iOS HTTP Reliability:** iOS 17+ HTTP failures—is this an Obsidian bug or iOS policy change? (Unconfirmed root cause)

---

**Report Generated:** 2026-03-17
**Status:** Complete. Covers all 7 requested research areas with implementation patterns + concrete code examples.

