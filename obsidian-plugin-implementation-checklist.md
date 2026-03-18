# Obsidian Plugin Development: Implementation Quick Reference

## Setup Checklist

- [ ] Clone obsidianmd/obsidian-sample-plugin
- [ ] `npm i` and verify node_modules installed
- [ ] Update manifest.json with your plugin info
- [ ] Set `"isDesktopOnly": false` if targeting iOS
- [ ] Run `npm run dev` (watch mode)
- [ ] Reload Obsidian to test

## Core API Patterns

### File I/O
```typescript
// Read
const content = await this.app.vault.read(file);

// Modify
await this.app.vault.modify(file, newContent);

// Create
await this.app.vault.create(path, content);

// Delete
await this.app.vault.trash(file); // or .delete()

// List
this.app.vault.getMarkdownFiles();
this.app.vault.getFiles();
```

### Event Listeners (IMPORTANT: Always use registerEvent)
```typescript
// Do this:
this.registerEvent(
  this.app.vault.on('modify', (file) => { /* ... */ })
);

// NOT this (causes memory leaks):
this.app.vault.on('modify', (file) => { /* ... */ });
```

### HTTP Requests
```typescript
import { requestUrl } from 'obsidian';

const response = await requestUrl({
  url: 'https://...',  // HTTPS only on iOS
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ /* ... */ }),
});

console.log(response.status, response.json, response.text);
```

### Background Tasks
```typescript
// Start interval (cleanup in onunload)
this.syncInterval = window.setInterval(() => {
  this.performSync();
}, 30000);

// Cleanup
onunload() {
  if (this.syncInterval) window.clearInterval(this.syncInterval);
}
```

### Debouncing (CRITICAL for event-driven sync)
```typescript
private debounceTimer: NodeJS.Timeout;

this.registerEvent(
  this.app.vault.on('modify', (file) => {
    clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => {
      this.syncToServer(file); // called once per 5 sec
    }, 5000);
  })
);
```

## iOS-Specific Checks

### Manifest
```json
{
  "isDesktopOnly": false,
  "minAppVersion": "1.0.0"
}
```

### Code
- ✅ Use `requestUrl()` for HTTP (not `fetch`)
- ✅ HTTPS only (no plaintext HTTP on iOS)
- ❌ Avoid NodeJS/Electron APIs (fs, path, ipcRenderer)
- ❌ No `require()` calls
- ✅ Use browser APIs only (localStorage, setTimeout, etc.)

### Testing
- Test on real iOS device (simulator may not catch issues)
- Verify Restricted Mode doesn't block plugin
- Check for console errors (no debugger, read forum logs)

## Sync Implementation Pattern (Recommended)

```typescript
class VaultSyncPlugin extends Plugin {
  private debounceTimer: NodeJS.Timeout;
  private syncInterval: NodeJS.Timeout;
  private syncQueue: Array<{ path: string; content: string }> = [];

  onload() {
    // Watch file changes (push)
    this.registerEvent(
      this.app.vault.on('modify', (file) => {
        this.scheduleSync(file);
      })
    );

    // Periodic poll (pull)
    this.syncInterval = window.setInterval(() => {
      this.pullChanges();
    }, 60000);

    // Manual sync button
    this.addRibbonIcon('sync-c-w', 'Sync', () => this.performSync());
  }

  onunload() {
    clearTimeout(this.debounceTimer);
    clearInterval(this.syncInterval);
  }

  private scheduleSync(file: TFile) {
    clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => {
      this.pushFile(file);
    }, 5000);
  }

  private async pushFile(file: TFile) {
    try {
      const content = await this.app.vault.read(file);
      await requestUrl({
        url: `${this.serverUrl}/api/vault/sync`,
        method: 'POST',
        body: JSON.stringify({
          file_path: file.path,
          content,
          mtime: file.stat?.mtime,
        }),
      });
      // Remove from queue if present
      this.syncQueue = this.syncQueue.filter(x => x.path !== file.path);
    } catch (error) {
      // Add to queue for retry
      this.syncQueue.push({
        path: file.path,
        content: await this.app.vault.read(file),
      });
    }
  }

  private async pullChanges() {
    try {
      const response = await requestUrl({
        url: `${this.serverUrl}/api/vault/changes?since=${this.lastSyncTime}`,
      });
      // Process downloaded files...
    } catch (error) {
      console.error('Pull failed:', error);
    }
  }

  private async performSync() {
    await this.pushPendingQueue();
    await this.pullChanges();
  }

  private async pushPendingQueue() {
    for (const item of this.syncQueue) {
      await this.pushFile(
        this.app.vault.getAbstractFileByPath(item.path) as TFile
      );
    }
  }
}
```

## Testing Checklist

- [ ] Create test vault with 10+ files
- [ ] Verify modify event fires on file change
- [ ] Verify debounce: 5 rapid edits = 1 sync call (not 5)
- [ ] Test offline: edit while server down, verify queue stores changes
- [ ] Test reconnect: queue clears when server comes back
- [ ] Test on iOS: real device, not simulator
- [ ] Verify HTTPS endpoints work
- [ ] Verify no HTTP plaintext on iOS
- [ ] Test with Tailscale network
- [ ] Verify settings saved/loaded correctly
- [ ] Check console for memory leaks (DevTools on desktop)

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Raw `on()` listener causes memory leak | Use `registerEvent()` for auto-cleanup |
| HTTP request fails with CORS error | Use `requestUrl()` not `fetch()` |
| Sync called 10x per keystroke | Add debounce (5-10 sec) |
| Plugin doesn't load on iOS | Set `isDesktopOnly: false` in manifest |
| HTTPS errors on iOS | Use only HTTPS endpoints |
| `vault.modify()` fails silently | Check requestSave debounce (2 sec delay) |
| Settings not persisting | Call `this.saveData()` after change |
| No error messages on iOS | Enable plugin on desktop, test logic there first |

## Minimal File Structure

```
my-plugin/
├── main.ts              # Plugin class (100-200 lines)
├── manifest.json        # Metadata
├── esbuild.config.mjs   # Build config (copy from sample)
├── tsconfig.json        # TS config (copy from sample)
├── package.json
└── .gitignore
```

## Deployment Steps

1. **GitHub Release:**
   - Tag: `git tag 1.0.0`
   - Build: `npm run build`
   - Create release with manifest.json + main.js + styles.css

2. **Community Store (optional):**
   - Fork obsidianmd/obsidian-releases
   - Add entry to community-plugins.json
   - PR with repo link

3. **Users Install:**
   - Browse "Community Plugins" in Obsidian
   - Search for plugin name
   - Install and enable

## Debugging Tips

**Desktop:**
- Open DevTools: Cmd+Option+I (Mac) / Ctrl+Shift+I (Windows)
- Check console for errors
- Use `console.log()` for debugging
- Hot reload plugin: Settings > Reload plugin

**iOS:**
- No browser console available
- Test logic on desktop first
- Check Obsidian forum for similar issues
- Create minimal reproduction test

## Resources

- [Official Sample Plugin](https://github.com/obsidianmd/obsidian-sample-plugin)
- [API Docs](https://docs.obsidian.md/Plugins/Vault)
- [Events Docs](https://docs.obsidian.md/Plugins/Events)
- [Community Forum](https://forum.obsidian.md/c/plugins/16)

