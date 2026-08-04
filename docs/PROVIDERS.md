# Providers

## `adspower-cdp`

Starts AdsPower and connects to `data.ws.puppeteer`.

If AdsPower returns `ws://127.0.0.1:port/...`, browser-auto-ops must run on the AdsPower host or use user-managed forwarding. v1 intentionally does not create SSH tunnels.

## `local-chrome`

Starts a new isolated Chrome profile:

```text
chrome.exe --remote-debugging-port=<port> --user-data-dir=<dir>
```

It does not attach to the user's default Chrome and does not automate Chrome's remote-debugging permission dialog.

## `cdp`

Connects to an existing endpoint:

```text
http://host:port
ws://host:port/devtools/browser/<id>
```

It does not own or stop external browsers.

