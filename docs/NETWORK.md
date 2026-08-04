# Network

v1 records network via Playwright page events:

- request
- response
- requestfailed
- response body best-effort capture

CLI:

```bash
bao network requests s_xxx --type xhr,fetch --filter /api/
bao network request s_xxx r_xxx
```

Future work:

- Direct CDP `Network.*` session per target/frame
- HAR export
- offline operation verification for Forge safe mode

