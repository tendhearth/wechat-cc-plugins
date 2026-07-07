# wechat-cc-plugins

The curated plugin registry (the "market") for
[wechat-cc](https://github.com/tendhearth/wechat-cc). `registry.json` is a
static index of installable plugins — Obsidian community-plugins.json /
Homebrew-tap style. It holds only **pointers**: each entry names a git source;
the plugin's actual files live in its own repo, versioned by tags.

## For users — point wechat-cc at this registry

```sh
export WECHAT_CC_PLUGIN_REGISTRY=https://raw.githubusercontent.com/tendhearth/wechat-cc-plugins/main/registry.json

wechat-cc plugin search            # browse (✓ installed / ⬆ update)
wechat-cc plugin install <name>    # git clone into the plugins dir (DISABLED)
wechat-cc plugin enable <name>     # then finish setup + restart the daemon
wechat-cc plugin upgrade --all     # pull newer versions
```

Or use the desktop dashboard's **插件 → 市场** section.

## Entry schema

```jsonc
{
  "name": "example-plugin",          // unique; ^[A-Za-z0-9][A-Za-z0-9_-]*$
  "version": "1.0.0",                // semver; MUST match the git tag + the
                                     // plugin's own wechat-cc.plugin.json version
  "displayName": "Example",          // optional
  "description": "…",                // optional, shown in search + market
  "author": "you",                   // optional
  "homepage": "https://…",           // optional
  "minWechatCcVersion": "0.6.4",     // optional; host older than this → withheld
  "source": {
    "type": "git",                   // only git today
    "url": "https://github.com/you/example-plugin",  // https only, public
    "ref": "v1.0.0"                  // tag (or branch) to clone/checkout
  }
}
```

> Installing runs third-party code, so entries are curated and land **disabled**
> until the operator enables them. Only list plugins whose repos are **public**
> (the market installs via `git clone`). First-party or private capabilities are
> shipped as **bundled plugins with wechat-cc**, not listed here.

## Submitting a plugin (curated via PR)

1. Your plugin is its own **public** git repo containing a
   `wechat-cc.plugin.json` manifest (see wechat-cc `docs/plugins.md`).
2. Publish a git **tag** matching the manifest `version` (e.g. `v1.0.0`).
3. Open a PR adding one entry to `registry.json`, sorted by `name`.
