# QAP reference

The [README](../README.md) is the tour; this page is the detail: the content layout, every `qap` command, the
dashboard, and the code map.

| Part | Where | What it does |
|---|---|---|
| The skill | `skill/` (`~/.claude/skills/qa-pass` is a symlink to it) | `SKILL.md`, the page template, `build.py` / `check.py` / `carry.py`, the page's own JS and CSS |
| `qap`, the CLI | `src/qap/` | Where a pass goes, the next pass number, carry / build / check, projects, folders and moves |
| The dashboard | `src/qap/web/` + `qap serve` | Icon tiles for projects, folders and subjects, a pass viewer with a selector made for 40+ passes, the search |
| Plugins | `src/qap/plugins.py`, `src/qap/core_plugins/` | Obsidian-style plugins ([plugins.md](plugins.md)); `git-storage`, the git backup, is the first |

The passes themselves are not here. They live in the content root, by default
`~/Desktop/Dev/ai/QAP/contents` (its own folder, never in this repository; `qap storage git init` can back it
up in a repository of its own).

## Run it

Nothing to install: the CLI is Python standard library only.

```bash
~/Desktop/Dev/ai/QAP/QAP/bin/qap list           # python3 >= 3.10, else falls back to uv run
uv run --project ~/Desktop/Dev/ai/QAP/QAP qap list
uv tool install ~/Desktop/Dev/ai/QAP/QAP         # optional: a `qap` on your PATH
```

Then `qap serve --open` and browse every pass at <http://127.0.0.1:8750>.

## The content layout

```
contents/
  projects.json                optional {default, projects: [{id, title, icon, color}]}
  <folder>/                    any depth; a folder holds folders and subjects
    folder.json                optional {title, icon, color, order, project}
    <subject>/                 one conversation thread
      subject.json             {title, icon, color, qa_project, sources, created}
      QA-PASS-1.src.html       the source of pass 1 (you or carry.py edit it)
      QA-PASS-1.html           the built page, self-contained (what the reader opens)
      img/                     the images of every pass, and the scripts that drew them
```

- A directory is a **subject** when it holds `subject.json` (or, without one, `QA-PASS-*` files). Every
  other directory is a **folder**.
- `qa_project` is the pages' `<meta name="qa-project">`. The pages keep their stars in the browser under
  that key, so every pass of a subject shares its stars.
- `sources` lists the places the passes came from. Those places are symlinks into the subject now, so old
  links keep working. `qap mv` re-points those symlinks when a subject moves.
- `icon` is an emoji or a built-in name (`qap icon --help`, or the picker in the dashboard). `color`
  (`#RRGGBB`) is optional. Without it, a tile takes a colour from its folder name.
- `order` in `folder.json` is either a number (this folder's rank among its siblings) or a list of child
  names (the order of its children). Anything else is listed folders first, then by title.
- **Projects** sit above the top-level folders (the **families**). A project is not a directory: it is an
  entry of `projects.json`, named `@<id>` wherever a path goes (`qap mv authz @personal`, `#/@work` in the
  dashboard). A top-level folder or subject joins one with `"project": "<id>"` in its own manifest; one
  without it belongs to the `default` project. Nothing moves on disk, so paths, links and symlinks stay
  valid, and a tree without `projects.json` reads exactly as before.
  - The first project created becomes the default, so it holds every family there is: on an existing tree,
    `qap project new work` is the whole migration.
  - When the default changes, the families that were in the old default only by being unassigned get its
    id written in, so no family ever changes project by itself; the default only decides where new
    families go.
  - Only top-level items have a project. Putting a deeper folder or subject in a project moves it up to the
    top level first (symlinks re-pointed, as `qap mv` does).

Where the content root is, first match wins: `--root`, the `QAP_CONTENT_ROOT` environment variable,
`~/.config/qap/config.json` (`qap config content_root <path>`), the default above.

## `qap` commands

Run a command without its arguments in a terminal and `qap` asks for them (folders and subjects come from
a numbered menu). Agents give every argument and add `--json` (no prompt, machine output, `{"ok": false,
"error": …}` and exit 1 on failure). `--yes` skips confirmations. A subject is named by its path, or by
its folder name, title or qa-project when that is unique.

| Command | Does |
|---|---|
| `qap config [key [value]] [--unset]` | Shows where the content and the skill are, or sets `content_root` / `skill_dir` |
| `qap list [path] [--passes]` | Shows the tree (`--passes`: every pass with its title) |
| `qap where <subject>` | Shows the subject's folder, qa-project, latest pass, next pass number and file names |
| `qap next <subject>` | Shows the next pass number, its `.src.html` / `.html` paths, and the source it carries from |
| `qap new-subject <folder>/<subject> --title --icon --qa-project [--project]` | Creates a subject with its `subject.json` and `img/`. `--project`: the project a new top-level folder joins (an existing one must already be in it) |
| `qap carry <subject> [--skip p7,p8] [--stars file] [--ai v\|Name\|Model]` | Starts the next pass: `carry.py` from the latest source, or the template for pass 1 |
| `qap build <subject> [--pass N \| --all] [--check]` | Runs `build.py`. `--all` rebuilds every page that has a source and keeps the old page when the new one fails `check.py` |
| `qap check <subject> [--pass N \| --all]` | Runs `check.py` |
| `qap mkdir <path> --title --icon [--project]` | Creates a folder |
| `qap mv <src> <dest>` | Moves a subject or folder into a folder (`/` is the top level), to a new path (move and rename), or into a project (`@id`) |
| `qap rename <path> <title>` / `qap icon <path> <icon> [--color]` | Changes what the tile shows (a project too: `@id`) |
| `qap project [list]` | The projects, their families and subject counts; the default is marked |
| `qap project new <id> [--title --icon --color --default]` | Creates a project; the first one is the default |
| `qap project move <folder\|subject> <project>` | Puts a family (or a top-level subject) in a project |
| `qap project set <project> [--title --icon --color --default]` / `qap project rm <project>` | Changes a project, or removes an empty one |
| `qap rmdir <path>` | Removes an empty folder. `qap` never deletes a pass |
| `qap place <file\|dir> <subject> [--as N] [--create] [--no-link]` | Moves a pass, or a whole old `choices/` folder, into a subject and leaves a symlink behind |
| `qap serve [--port N] [--open]` | Starts the dashboard on 127.0.0.1 |
| `qap plugins [list \| enable \| disable \| config \| install \| remove]` | Plugins: on / off, settings, install from a folder or a git URL ([plugins.md](plugins.md)) |
| `qap storage git init --remote <url> [--branch main]` | Backs the content root up in a git remote, or restores a backup into an empty content root |
| `qap storage git sync [-m MSG] [--no-push]` | Commits everything, pulls (merge or rebase), pushes. Never forced |
| `qap storage git status [--fetch]` / `log [-n N]` | What is not backed up yet, a conflict, warnings / the latest commits |
| `qap storage git commit [-m MSG]` | Commits here only, without the network |
| `qap storage git resolve --mine \| --theirs` | Settles a conflict by keeping one side's files; the other side stays in the history |

Example, for an agent:

```console
$ qap next rbac --json
{
  "ok": true,
  "subject": "authz/rbac",
  "n": 43,
  "src": "/Users/iyan/Desktop/Dev/ai/QAP/contents/authz/rbac/QA-PASS-43.src.html",
  "html": "/Users/iyan/Desktop/Dev/ai/QAP/contents/authz/rbac/QA-PASS-43.html",
  "img": "/Users/iyan/Desktop/Dev/ai/QAP/contents/authz/rbac/img",
  "carry_from": null
}
```

## The dashboard

`qap serve` serves the dashboard and the content from **one origin** (`http://127.0.0.1:8750`, or the
next free port). This matters because the pages keep their stars and theme in `localStorage`, and the
browser keeps `localStorage` per origin. Served this way, a star made in pass 3 shows in pass 2.

- **Projects, folders and subjects are tiles.** Each tile is a rounded square in the item's colour, with
  its icon inside and its name under the icon, like the map in `~/.dotfiles/README.md`. Folder tiles have
  a tab. Subject tiles carry their pass count. With projects, the home shows one bigger box per project
  (`#/@work`), with a row of its families' small boxes under it; a project shows its families.
- **Click a subject** and its latest pass opens in a large frame. The bar holds the pass selector:
  - `‹` and `›` step through the passes;
  - a strip shows every pass number;
  - "Pass N ▾" opens a list you can search by number, title or date;
  - `↗` opens the page alone.
- **Keys:** `←` and `→` (or `[` and `]`, which also work inside the page) go to the previous and next
  pass. `Home` and `End` go to the first and latest. On a subject `/` opens the pass list.
- **Search** (top right on every view, just left of `‹` on a subject; `⌘K` / `Ctrl+K` anywhere, the framed
  pass included; `/` outside a subject). One dialog over every project, family, subject and pass: empty, it
  shows the home (the projects, then the subjects updated last); typing ranks the same boxes as cards,
  grouped projects, families, subjects, passes, each with its project › family › subject.
  - Searched: titles, folder names, qa-projects, and per pass its `<h1>` (without "Q&A pass N —"), kicker
    and section titles (every `h2` with an id). A section match opens the pass at that section.
  - Fuzzy (`web/fuzzy.js`): every word must match. Whole field, start, word start, anywhere, plurals
    (`retry` ~ `retries`), no separators (`inv204` ~ `inv-204`), letters in order (`dbmig`), one typo
    (`migartion`), accents ignored; a word of digits only matches whole numbers (`3` is not `13`).
  - Keys: `↑` `↓` the row above or below, `Tab` the next card, `Enter` opens (`⌘Enter` a new tab), `Esc`.
  - A pass page opened alone from `qap serve` has a Search button in its top row, left of the theme toggle:
    it loads the dashboard's own `/ui/search.js`, and a result opens in the dashboard. Opened as a file (or
    from another server) the page has no button, and `⌘K` or `/` says to open it through `qap serve`.
- **Organise:**
  - "+ New folder" asks for a title, an icon and a colour (in a project, the folder is a family of it);
    "+ New project" on the home does the same for a project;
  - drag a tile onto a folder or project tile, or onto a name in the breadcrumb to move it up (Undo in the
    toast);
  - each tile's `⋯` menu (or a right-click) has Rename, Icon and colour, Move to… (projects first), and
    Delete for an empty folder or project.
- The theme is the same as the pages' (`qa-theme`), so one toggle switches both. The dashboard also works
  at phone width.

- **Plugins**: the ⧉ button in the top bar lists the plugins' commands (Ctrl/⌘ ⇧ P) and opens the Plugins
  page (`#/~plugins`): each plugin's on/off switch, settings and commands. Plugins add status items (the
  `git` pill) and views (`#/~plugins/git-storage/status`).

The server is Python's `http.server`, bound to 127.0.0.1 only. It has a small JSON API (`GET /api/tree`,
`GET /api/search`, `POST /api/mkdir|mv|rename|icon|rmdir|project`; a project is `@id` in a path) that
calls the same functions as the CLI (`qap.layout`, `qap.search`). It
refuses writes that do not come from its own origin (it checks the Host and Origin headers, and requires a
JSON body). Plugins add `GET /api/plugins`, `POST /api/plugins/<id>/enable|disable|settings|run/<command>`,
their own `/api/plugins/<id>/<route>` (POSTs pass the same guards) and `/plugins/<id>/web/<file>`.

## How the skill uses it

`skill/SKILL.md` § "Files: where a pass goes" tells an agent to:

1. Find the subject with `qap list --json`, or create it with `qap new-subject` (asking the user for the
   folder, and for a new family its project, when none fits).
2. Start the round with `qap carry <subject>`.
3. Write the source, then run `qap build <subject> --check`.
4. Do the render check through `qap serve`.

The skill's scripts stay the only implementation. `qap` only picks the files and runs them.

## Code map

```
bin/qap                 shim: python3 -m qap with src/ on the path (uv run fallback)
src/qap/config.py       content root and skill dir resolution, ~/.config/qap/config.json
src/qap/passes.py       pass file names, titles, sections and kicker, next pass number
src/qap/layout.py       the tree, resolve, and every write (mkdir, new subject, move + relink, place, rmdir,
                        projects: new, assign, remove)
src/qap/search.py       the search index (GET /api/search)
src/qap/skill.py        build/check/carry wrappers, template seeding, safe rebuild
src/qap/cli.py          argparse commands, prompts (prompt.py), --json output
src/qap/server.py       http.server: static dashboard, /c/ content, JSON API, plugin routes
src/qap/plugins.py      the plugin host: manifests, discovery, on/off, Plugin (onload/onunload, add_command,
                        register_route/event/interval, settings, data.json), events
src/qap/plugin_cli.py   `qap plugins …` and the commands plugins add (qap storage git …)
src/qap/core_plugins/   core plugins; git-storage/: main.py (wiring), store.py (git), web/ (pill + view)
src/qap/web/            index.html, style.css, app.js (router), tiles.js, viewer.js, dialogs.js, icons.js, api.js,
                        dom.js; search.js + search.css (the dialog, also loaded by pass pages), fuzzy.js (ranking);
                        plugins.js + plugins.css (the dashboard's plugin host and Plugins page)
examples/plugins/       build-log: the example plugin
skill/assets/           qa-pass.js / qa-pass.css, inlined into every built page
tests/                  unittest: layout functions, projects, CLI --json, the server, the search index and
                        fuzzy.js (run with node when it is installed), plugins, git-storage end to end (local bare
                        repos in a temp dir)
```

Run the tests with `uv run --project . python -m unittest discover -s tests`.
