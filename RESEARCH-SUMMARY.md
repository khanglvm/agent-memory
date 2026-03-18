# Obsidian Plugin Development Research: Executive Summary

**Research Date:** 2026-03-17
**Scope:** 7 key research areas on custom sync plugin development
**Status:** ✅ Complete

---

## Quick Answers to Your Questions

### 1. **Obsidian Plugin API** ✅

**Can plugins:**
- ✅ **Watch file changes?** Yes. Use `vault.on('modify', 'create', 'delete', 'rename')`
- ✅ **Read/write files?** Yes. `vault.read()`, `vault.modify()`, `vault.create()`, `vault.trash()`
- ✅ **Make HTTP requests?** Yes. Use `requestUrl()` (bypasses CORS). Avoid `fetch()`.
- ✅ **Run background tasks?** Yes. `setInterval()` works, but stops when app closes
- ✅ **Access file metadata?** Partially. `file.path`, `file.stat.mtime`. No official YAML parser.
- ✅ **Hook into Obsidian events?** Yes. 6 vault events available.

**Key constraint:** Must debounce events—Obsidian auto-saves every 2 sec, creating event spam.

---

### 2. **iOS Community Plugins** ✅

**Do they work?** Yes, since 2023.

**Same API?** Mostly yes, with constraints:
- ✅ File read/write works
- ✅ Event listeners work (possibly rate-limited)
- ❌ HTTP only (no plain HTTP; App Store blocks it)
- ❌ NodeJS/Electron APIs unavailable
- ❌ No debugging (no browser console)
- ⚠️ Restricted Mode enabled by default (blocks plugin activation until user disables)

**Set in manifest:** `"isDesktopOnly": false` to enable iOS.

---

### 3. **Plugin Development Stack** ✅

**Language:** TypeScript → esbuild → JavaScript
**Build:** `npm run dev` (watch), `npm run build` (production)
**Output:** `main.js`, `manifest.json`, `styles.css`
**Template:** Use [obsidianmd/obsidian-sample-plugin](https://github.com/obsidianmd/obsidian-sample-plugin)

**Keep plugins lightweight.** Avoid `axios`, use built-in `requestUrl()`.

---

### 4. **Reference Plugins to Learn From** ✅

**Remotely Save** (Push-based sync)
- Syncs vault to S3/WebDAV/Dropbox/OneDrive/etc.
- Architecture: Event listener → debounce → upload
- Code pattern: FakeFs abstraction layer (easy to add backends)
- Conflict handling: Basic (free) vs smart merge (PRO)

**Self-hosted LiveSync** (Bidirectional CouchDB)
- Uses CouchDB replication protocol (real-time, bidirectional)
- Auto-conflict resolution via CouchDB
- Works on iOS
- Code pattern: ModuleReplicator class (sync queue management)
- Better for true real-time sync

---

### 5. **Self-hosted LiveSync** ✅

**How it works:**
1. Local PouchDB mirrors vault files + metadata
2. CouchDB on server holds vault data
3. PouchDB ↔ CouchDB replicate bidirectionally (native protocol)
4. Conflicts auto-resolved or marked for manual resolution
5. Offline changes queued, synced when reconnected

**Setup:** Docker CouchDB + LiveSync plugin + setup URI for device pairing

**Verdict:** Mature pattern. CouchDB replication protocol is battle-tested. Worth studying if building custom REST server.

---

### 6. **Tailscale + Obsidian iOS** ✅

**Does integration exist?** No dedicated Obsidian plugin for Tailscale.

**Can it work?** Yes. Workaround pattern:
1. Install Tailscale app on iOS (VPN mode)
2. Plugin targets Tailscale IP (e.g., `https://100.67.89.10/api/sync`)
3. `requestUrl()` reaches Tailscale network IPs like any endpoint
4. Community confirms: SyncThing + Tailscale + Obsidian iOS working

**Constraint:** iOS allows only one VPN "On Demand" at a time. Document this in README.

---

### 7. **Key Constraints** ✅

| Constraint | Impact | Workaround |
|-----------|--------|-----------|
| Event spam from auto-save | 5+ events per edit | Debounce 5-10 sec |
| `fetch()` CORS error | Requests blocked | Use `requestUrl()` |
| No HTTP on iOS | Apple policy | Use HTTPS only |
| No background timers | Sync stops when app closed | Queue changes, sync on restart |
| No YAML parser API | Frontmatter handling manual | Regex parse or js-yaml library |
| Memory leaks | Raw event listeners not cleaned up | Use `registerEvent()` |
| iOS Restricted Mode | Plugin won't activate | Document: "disable Restricted Mode" |

---

## Recommended Architecture (Custom REST Server)

### Two-Phase Sync:

**Phase 1: Push (Event-Driven)**
- Listen to `vault.on('modify')`
- Debounce 5 sec
- POST file to `/api/vault/sync`
- Store offline queue on failure

**Phase 2: Pull (Polling)**
- Every 60 sec, poll `/api/vault/changes?since=lastTime`
- Download new files
- Detect conflicts (hash comparison)
- Create `.conflict` versions if collision

### Minimal Server API (3 endpoints):
```
POST /api/vault/sync         (push file)
GET  /api/vault/changes      (pull changes)
DELETE /api/vault/files/{path}
```

### Key Implementation Details:
- Store file mtime + hash on server
- Implement offline queue in plugin settings
- Retry with exponential backoff
- UI status indicator (ribbon icon + status bar)
- Conflict detection via content hash

---

## Implementation Phases

| Phase | Duration | Deliverable | iOS Ready? |
|-------|----------|-------------|-----------|
| 1. Foundation | Week 1-2 | File I/O + events + HTTP | No |
| 2. Sync Engine | Week 2-3 | Push sync + offline queue | No |
| 3. Bidirectional | Week 3-4 | Pull sync + conflict handling | No |
| 4. iOS Support | Week 4-5 | HTTPS, Tailscale, Restricted Mode docs | Yes |
| 5. Distribution | Week 5-6 | GitHub release + community store PR | Yes |

---

## Code Example (Minimal Push Sync)

```typescript
import { App, Plugin } from 'obsidian';
import { requestUrl } from 'obsidian';

export default class SyncPlugin extends Plugin {
  private debounceTimer: NodeJS.Timeout;

  async onload() {
    this.registerEvent(
      this.app.vault.on('modify', (file) => {
        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => {
          this.sync(file);
        }, 5000);
      })
    );
  }

  async sync(file) {
    const content = await this.app.vault.read(file);
    await requestUrl({
      url: 'https://your-server.com/api/vault/sync',
      method: 'POST',
      body: JSON.stringify({
        path: file.path,
        content,
        mtime: file.stat?.mtime,
      }),
    });
  }

  onunload() {
    clearTimeout(this.debounceTimer);
  }
}
```

---

## Resources

**Official:**
- [Obsidian Plugin API](https://docs.obsidian.md/Plugins/Vault)
- [Sample Plugin](https://github.com/obsidianmd/obsidian-sample-plugin)
- [Community Plugins Guide](https://help.obsidian.md/community-plugins)

**Reference Implementations:**
- [Remotely Save (GitHub)](https://github.com/remotely-save/remotely-save)
- [Self-hosted LiveSync (GitHub)](https://github.com/vrtmrz/obsidian-livesync)

**Community:**
- [Obsidian Forum](https://forum.obsidian.md/c/plugins/16)

---

## Files in This Research

1. **obsidian-plugin-development-comprehensive-research.md** (12 sections, 1000+ lines)
   - Complete deep dive on all 7 research areas
   - Code examples and patterns
   - Sync architecture recommendations

2. **obsidian-plugin-implementation-checklist.md**
   - Quick reference for development
   - API patterns cheat sheet
   - Testing checklist
   - Common pitfalls

3. **RESEARCH-SUMMARY.md** (this file)
   - Executive summary
   - Quick answers
   - Recommended architecture

---

## Next Steps (For Implementation)

1. **Clone sample plugin:** `git clone https://github.com/obsidianmd/obsidian-sample-plugin`
2. **Set up TypeScript dev:** `npm i && npm run dev`
3. **Implement Phase 1:** File operations + vault events + requestUrl HTTP
4. **Test on desktop:** Verify debouncing and sync logic
5. **Add iOS support:** Set manifest `isDesktopOnly: false`, test on device
6. **Polish & distribute:** GitHub release, community plugins PR

---

## Unresolved Questions (For Future Research)

1. **iOS Background Sync:** Does Obsidian's sync work when app backgrounded?
2. **Plugin Size Limits:** Hard cap for community store submission?
3. **YAML Preservation:** Does vault.modify() preserve frontmatter formatting?
4. **HTTP Rate Limiting:** Built-in limits in requestUrl()?
5. **iOS Event Rate Limiting:** Are vault.on() events batched on iOS?

---

**Status:** ✅ Research Complete
**Confidence Level:** High (verified with official docs + working plugin source code)
**Ready for:** Implementation (proceed to Phase 1)

