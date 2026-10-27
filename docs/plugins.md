# Plugins

A plugin adds commands, reactions and dashboard parts to `qap` without touching its code. The model is
Obsidian's: a folder with a `manifest.json` and a main module, an `onload()` that registers what the plugin
adds, an `onunload()`, and a list where you turn each plugin on or off. Everything a plugin registered is
removed when it is turned off.

The first plugin is the git backup, [`git-storage`](#git-storage-the-first-plugin), which ships with qap.
The smallest complete example is [`examples/plugins/build-log`](../examples/plugins/build-log).

## Where plugins live, and who turns them on

| Kind | Folder | On by default |
|---|---|---|
| Core | `src/qap/core_plugins/<id>/`, shipped with qap | Yes |
| Community | `~/.config/qap/plugins/<id>/`, put there by `qap plugins install` | No: you turn it on |

- The on/off list is `~/.config/qap/plugins.json`. A plugin's settings and other data are in
  `~/.config/qap/plugins/<id>/data.json`.
- Nothing of a plugin lives in the content root. The content can be pulled from a git remote, and pulled
  content must never run code.
- A plugin runs Python with your permissions, like an Obsidian community plugin runs JavaScript. Read a plugin
  before you turn it on.
- A community plugin is turned on from a terminal only. The pass pages are served from the dashboard's origin,
  and a pass can come from someone else's machine through the git backup. Such a page could press the
  dashboard's switch, so the switch can turn a community plugin off but never on.

```bash
qap plugins                              # every plugin, on or off, and the commands it adds
qap plugins install ./my-plugin          # copy a folder (--link: symlink it, for development)
qap plugins install https://github.com/you/qap-my-plugin.git
qap plugins enable my-plugin             # the dashboard's Plugins page (⧉ → Plugins…) can only turn it off
qap plugins config my-plugin             # its settings; `qap plugins config my-plugin key value` sets one
qap plugins disable my-plugin
qap plugins remove my-plugin             # community plugins only; a core plugin is disabled instead
```

## The folder

```
my-plugin/
  manifest.json
  main.py            one Plugin subclass; other .py files beside it import as `from .helpers import x`
  web/main.js        optional: the dashboard part
  web/style.css      optional
```

`manifest.json`:

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Lowercase letters, digits and single hyphens. A community plugin's folder is named after it. |
| `name` | yes | Shown in the lists. |
| `version` | yes | `x.y.z`. |
| `minAppVersion` | yes | The oldest qap it runs on (`x.y.z`). An older qap lists it and does not load it. |
| `description` | yes | One or two sentences. |
| `author`, `authorUrl` | no | |
| `main` | no | The Python module, default `main.py`. |
| `web` | no | `{"main": "web/main.js", "style": "web/style.css"}`. Only the `web/` folder is served. |

## The Python side

```python
from qap.plugins import Plugin, Setting


class Hello(Plugin):
    def onload(self):
        self.add_settings(Setting("greeting", "Greeting", "hello"))
        self.add_command("say", "Say it", self.say,
                         args=[(["--name"], {"default": "world"})])   # qap hello say --name Iyan
        self.register_event("pass_built", self.built)

    def say(self, opts):
        return {"text": f"{self.settings['greeting']}, {opts.name}"}  # --json prints the rest as data

    def built(self, payload):
        return {"text": f"hello: {payload['subject']} was built"}    # shown under `qap build`
```

`onload()` runs whenever qap loads the plugin. That happens in every `qap` command, so `onload()` should only
register things. `onunload()` runs when the plugin is turned off or qap exits.

| Method | What it adds | Removed on unload |
|---|---|---|
| `add_command(id, name, callback, cli=…, args=[…], dashboard=True)` | A CLI command and a dashboard command. `cli` is the words after `qap` (default `<plugin id> <command id>`; words shared by several plugins become a group, such as `qap storage git …`). `args` are `(flags, argparse kwargs)` pairs. `callback(opts)` gets the args by their dest names, plus `opts.source` (`"cli"` or `"dashboard"`), `opts.json` and `opts.interactive`. It returns `{"ok": bool, "text": "…", **data}`. | yes |
| `register_route(method, path, handler)` | `GET` or `POST /api/plugins/<id>/<path>` on `qap serve`. `handler(body)` returns a dict. A GET gets its query string as the body. A POST passes the same guards as the dashboard's own writes: it must come from the dashboard's origin, with a JSON body. A GET must not change anything, because any web page can make the browser send one (it just cannot read the answer). | yes |
| `register_event(name, handler)` | A reaction to an event (below). `handler(payload)` may return `{"text": …}`. | yes |
| `register_interval(seconds, fn)` | Calls `fn` every `seconds` while `qap serve` runs. `seconds` can be a function, read each time, and `0` pauses it. Nothing runs in one-shot CLI commands. | yes |
| `add_settings(Setting(key, label, default, help, choices))` | The plugin's settings tab, in `qap plugins config <id>` and on the dashboard's Plugins page. The type comes from the default (bool, int or str), and `choices` turns a str into a pick list. Read the values with `self.settings`. | yes |
| `register(fn)` | Any other cleanup. | runs it |
| `load_data()` / `save_data(dict)` | The plugin's `data.json`, which the settings share. | |
| `self.app` | `root` (the content root), `mode` (`"cli"` or `"serve"`), `emit(event, payload)`, `log(msg)`, `plugins`. | |
| `self.log(msg)` | A line on stderr, prefixed with the plugin id. | |

Errors stay inside the plugin. A plugin that fails to load is listed with its error. A handler that raises is
logged and the other handlers still run. A failing route returns a 500 for that one call.

### Events

| Event | When | Payload (plus `root` and `mode`) |
|---|---|---|
| `startup` | `qap serve` is listening. It runs in a background thread so the dashboard is not held back. | `url` |
| `shutdown` | `qap serve` stops. | |
| `pass_built` | After `qap build`, once per command, whether the build passed or not. What handlers return is printed under the build and added to `--json` as `plugins`. | `subject`, `ok`, `pages`, `source`, `interactive` |
| `content_changed` | After a write from the CLI (`new-subject`, `mkdir`, `mv`, `rmdir`, `rename`, `icon`, `place`, `carry`, `project new\|move\|set\|rm`) or from the dashboard (`mkdir`, `mv`, `rename`, `icon`, `rmdir`, `project`). | `action`, `source` (`"cli"` or `"dashboard"`), `project_action` (`qap project …`), `request` (the dashboard's JSON body) |

A plugin can emit its own events with `self.app.emit("<plugin id>:<event>", {...})`.

## The dashboard side

When a plugin is on and its manifest has `web.main`, the dashboard imports that module and calls its
`onload(app)`. Everything it adds through `app` is removed when the plugin is turned off. `onunload()` is
optional.

```js
export function onload(app) {
  app.addStatusItem({ text: "hi", title: "Hello plugin", onclick: () => { location.hash = app.viewHref("main"); } });
  app.addCommand({ id: "say", name: "Hello: say it", run: async () => {
    const r = await app.run("say", { name: "dashboard" });        // the Python command
    app.toast(r.text || r.error, { error: !r.ok });
  } });
  app.registerView("main", { title: "Hello", render: (box, tools) => { box.append(app.el("h1", { text: "Hello" })); } });
}
```

| `app.` | Does |
|---|---|
| `addStatusItem({text, title, onclick})` | Adds a button to the top bar, left of the ⧉ plugins menu, and returns it. |
| `addCommand({id, name, run})` | Adds an entry to the ⧉ menu (Ctrl/⌘ ⇧ P). |
| `registerView(id, {title, render(box, tools)})` | A page at `#/~plugins/<plugin id>/<id>` (`app.viewHref(id)`). `tools` is the top bar's tool area. |
| `request(path, body?)` | Calls the plugin's routes: GET without a body, POST with one. Returns the JSON and does not throw on `{ok: false}`. |
| `run(command, args)` | Runs one of the plugin's Python commands (`POST /api/plugins/<id>/run/<command>`). |
| `on("tree" \| "route" \| "settings", fn)` | Hears dashboard events: `tree` (the content was reloaded), `route` (the hash changed), `settings` (a setting was saved on the Plugins page). |
| `registerInterval(fn, ms)`, `register(fn)` | A timer, and any other cleanup. |
| `refresh()` | Reloads the tree and redraws the page. |
| `el`, `toast`, `dialog`, `menu` | The dashboard's own UI helpers (`dialogs.js`). |

The dashboard's `#/~plugins` page is the community-style list. It shows every plugin with its on/off switch,
its settings tab (drawn from its `Setting`s) and its commands. Commands that need no input have a Run button.

## git-storage, the first plugin

`git-storage` is a core plugin built only on the API above. Read
[`src/qap/core_plugins/git-storage/main.py`](../src/qap/core_plugins/git-storage/main.py) for the wiring
and `store.py` for the git work. What it registers:

- **Commands**: `qap storage git init | sync | status | log | commit | resolve`.
- **Events**:
  - `pass_built`: it syncs after each build;
  - `startup`: it syncs when `qap serve` starts.
- **An interval**: it syncs every `auto_sync_minutes` while `qap serve` runs.
- **A route**: `GET status`.
- **Ten settings**.
- **A dashboard part**: a status pill, a "Git backup" view and two ⧉ commands.

What it backs up: the `.gitignore` it writes leaves out the built pages that have a source; `store.py` adds the
other pages with `git add -f` and rebuilds the pages of the sources a restore or a pull brings in (`qap.skill`).

It stays inert until `qap storage git init` has run for the current content root, so having it on costs
nothing. How to use it is in the [README](../README.md#store-your-passes-in-git).
