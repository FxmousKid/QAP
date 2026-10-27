# QAP

Tooling for **QA passes**: the pages an AI agent writes, one per round of a design conversation, for a human to read
and answer.

![A project in the dashboard: its families and subjects as coloured icon tiles](docs/img/project.png)

## A QA pass

One self-contained HTML page that quotes you point by point, answers each point in its own thread (earlier rounds
folded), and ends with numbered decisions, each with a default.

<p>
  <img src="docs/img/pass.png" width="49%" alt="A pass page: a subject's thread, its earlier round unfolded, and two decision boxes with their defaults">
  <img src="docs/img/stars-dark.png" width="49%" alt="The same page in dark mode with the View stars dialog listing four starred messages">
</p>

Light and dark themes, a contents pane, stars that carry over to the next pass, links that open the folds they point
into, and a button back to where you clicked. CSS, JS and images are inlined: the page opens offline.

## `qap`, the CLI

```bash
qap new-subject payments/retries --title "Payment retries" --icon chart --qa-project retries
qap carry retries              # start the next pass: fold the last round, add the new round's placeholders
qap build retries --check      # build the page (links, labels, inlined images), then lint it
qap list                       # projects, families, subjects and their passes
qap serve --open               # the dashboard
```

Agents add `--json`: no prompts, JSON out. `skill/` is the `qa-pass` agent skill that tells an agent how to write a
pass and when to call `qap`.

## Projects

A **project** (work, personal…) holds **families** (the top-level folders: Payments, Platform…), which hold
**subjects** (Payment retries…), which hold the **passes**. The home shows one box per project, so work and personal never mix.

![The home: a Work box and a Personal box, each with the families it holds under it](docs/img/dashboard.png)

```bash
qap project new work --title Work --icon briefcase   # the first project holds every family there is
qap project new personal --title Personal --icon home
qap project move side-projects personal              # or drag the family's tile onto the project
qap mkdir garden --title Garden --project personal   # a new family, straight in its project
```

A project is an entry of `projects.json` at the content root, and a family joins it through `"project"` in its own
`folder.json`. No file moves, so every link and symlink keeps working; without `projects.json` nothing changes.

## Search

Fuzzy search over every project, family, subject and pass (titles, folder names, each pass's heading and section
titles), top right on every view and just left of `‹` on a subject. `⌘K` (`Ctrl+K`) anywhere, `/` outside a subject.
Empty, it shows the home; typing ranks the same boxes, with project › family › subject under each. `Enter` opens,
at the matching section when a section matched.

<p>
  <img src="docs/img/search-home.png" width="49%" alt="The search dialog, empty: the two project boxes and the six subjects updated last, as cards with their icon boxes">
  <img src="docs/img/search.png" width="49%" alt="The search dialog for 'retry': the subject Payment retries, then its three passes, the matched words highlighted">
</p>

A pass opened alone from `qap serve` has the same Search button in its top row; opened as a file it has none.

## The dashboard

`qap serve` serves the dashboard and every pass from one local origin, so stars and the theme follow you from pass to
pass. Open a subject and its latest pass shows, with a pass selector made for 40+ passes.

![The viewer: a subject's latest pass with the searchable list of its passes open](docs/img/viewer.png)

## Run it

```bash
uv run qap --help                      # or bin/qap: Python 3.10+, standard library only
python3 examples/make_demo.py /tmp/qap-demo && bin/qap serve --root /tmp/qap-demo --open
```

Passes live outside this repo, in a content root (`--root`, `QAP_CONTENT_ROOT` or `qap config content_root <path>`).
Everything else: [docs/reference.md](docs/reference.md).
