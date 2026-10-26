---
name: qa-pass
description: "Write a QA pass: a self-contained HTML conversation log that quotes the user point by point, answers each point in its own folded thread, puts every decision in a box with a default, and carries graphs, plots and screenshots. Use when the user says \"make a QA pass\", \"put that in a QA pass\", \"QA pass of everything\", answers a previous pass point by point, or after a study and before writing code (study → QA pass → answers → code)."
---

# QA pass: a conversation log, not a spec

A QA pass is one HTML page per round of a design or decision conversation. It quotes the user, answers them
**point by point**, keeps each subject's earlier back-and-forth folded in its own thread, and ends with the
decisions the user must take, each with a default. The reference layout is RBAC
`authz/rbac/QA-PASS-1.html` … `QA-PASS-19.html` in the content root (later RBAC passes drifted into question cards only:
don't copy those).

The page comes with this behaviour built in; you never write it by hand:
- **Light/dark toggle**, top right, next to View ★s. It follows the system by default and remembers the choice.
- **A contents pane that never moves the article.** "☰ Contents" (top left) or the `\` key opens and closes it.
  - The article reserves the pane's gutter whether it is open or not, so opening it shifts nothing.
  - On wide windows the pane and the top buttons hug the article; on narrow ones the pane slides over the page.
  - It highlights the section being read, and its state is remembered.
- **Speaker labels.** The user is **"Me"** (they read the page: "Me" is them, never you). The AI is its **logo +
  name + model in the vendor colour**: `{{AI:claude|Claude|Opus 5.5}}` (vendors: `claude`, `openai`, `gemini`,
  `other`). Each label also shows which pass the message comes from.
- **Stars.** Every message (theirs or yours, open or folded) gets a ☆ at the right of its label; it turns yellow
  when starred. **"View ★s"** (top right, the mirror of Contents) opens a dialog: a reference list of the starred
  messages grouped by subject, with author, pass and a one-line excerpt, never the full message. A click jumps to
  the message and unfolds its thread. "Copy list" copies the references, so the user can paste them in a reply.
  Stars are kept per project (`<meta name="qa-project">`) in the browser, so they survive into the next passes,
  as long as message ids stay stable and the passes are opened the same way (Chrome shares storage between
  `file://` pages; a viewer that keeps storage per file does not, and the dialog then says so). When the user
  pastes the dialog's "Copy list" with their answers, pass it to `carry.py --stars` (below): the next pass is
  built with those stars, whatever the viewer.
- **Deep links.** `QA-PASS-N.html#p3-1a` opens the fold that holds message `p3-1a` and flashes it. A link in
  the text to any `#id` (a subject, a need item, a decision box, a folded message) does the same, and the
  browser's Back returns to the sentence the reader clicked.
- **Back to where I clicked.** After a jump through a link in the text (or a row of View ★s), a faint
  "↩ Back to subject NN" (or "↩ Back to What I need from you") button shows in the top row, right of
  ☰ Contents, so it never covers the header or the line a jump lands on; on a phone it keeps only its arrow
  (the label stays in its tooltip). It returns to the link, reopening its folds, and flashes it. Jumps stack
  ("+2"); it fades 20 s after the last jump (hovering keeps it) and hides once nothing is left to return to.
  The browser's Back does the same thing; the key is `b`.
- **Responsive to the screen.** The page detects the pixel ratio, the window width tier (`xs`…`xxl`) and
  ultrawide screens, sets them on `<html>` (`data-dpr`, `data-size`, `data-ultrawide`), and re-detects on
  resize, zoom or a move to another screen.
  - Wide windows (ultrawide, 4K) get a larger root font (everything is in `rem`, no CSS zoom), a wider pane and
    wider figures, tables and diagrams. Prose and message boxes stay at a readable line length.
  - 1× screens get subpixel font rendering, sharper than the Retina-tuned default.
  - The footer prints what was detected ("Rendering for: screen … · pixel ratio … · layout …"), so the user
    can check it.

## The rule that comes before everything: say when a connection is missing

QA passes are built from real sources: Granola notes, Linear tickets, Slack threads, Braintrust traces,
PostHog, Supabase, Sentry, GitHub, the browser (Playwright). **If any MCP server or connection you need is
unavailable, failing, unauthenticated or timing out, tell the user, every time:**

- **In the chat:** name the server, the exact error, and what it blocks. Say how to fix it, for example:
  - `/mcp` to reconnect;
  - `claude mcp login granola`;
  - a `gcloud auth login`.
- **In the page:** add a visible callout in the affected section, saying that this part is unverified
  because a named source was not reachable.
- **Never:**
  - skip a source silently;
  - answer from memory as if you had read it;
  - quietly use a weaker substitute without saying so.

  If you fall back (another tool, a cached file), say which one, and what it can and cannot prove.
- A failed connection is not a missing capability. Don't conclude that "there is no access". Report the
  failure so the user can retry.

## When to use

- The user asks for a QA pass, or replies to one point by point (`"your sentence" : my reply`).
- A study, audit or design run finished and code would come next. Stop on a QA pass first: read-back, plan in
  plain words, numbered decisions with options and a recommended default. Wait for the answers. "Go ahead" is
  not approval of a plan the user has not seen.

## Files: where a pass goes (ask `qap`, never guess)

Every QA pass lives in one content tree, browsed in a dashboard (`qap serve`):

```
~/Desktop/Dev/ai/QAP/contents/      (qap config content_root; QAP_CONTENT_ROOT wins)
  <folder>/ …                              folders nest; folder.json {title, icon, order}
    <subject>/                             subject.json {title, icon, qa_project, sources, created}
      QA-PASS-N.src.html                   ← you edit this (qap carry writes it)
      img/                                 ← PNG/SVG/JPG for every pass (+ the scripts that drew them)
      QA-PASS-N.html                       ← built, self-contained, the file you hand over
```

`qap` (repo `~/Desktop/Dev/ai/QAP/QAP`, run `~/Desktop/Dev/ai/QAP/QAP/bin/qap …`, or
`uv run --project ~/Desktop/Dev/ai/QAP/QAP qap …`) places and builds passes. Agents: always pass every
argument and `--json`; it never prompts then. A subject is named by its path (`db-migration-v3/interaction`)
or, when unique, its folder name, title or qa-project.

```bash
Q=~/Desktop/Dev/ai/QAP/QAP/bin/qap
$Q list --json                         # folders, subjects, pass counts: find the subject first
$Q where interaction --json            # its folder, qa-project, latest pass, next pass number and file names
$Q new-subject db-migration-v3/billing --title "Billing (PRD-120)" --icon 💳 --qa-project v3-billing --json
                                       # a new subject: ask the user which folder if no folder fits
$Q carry interaction [--skip p7,p8] [--stars stars.txt] --json
                                       # starts the next pass: carry.py from the latest source, or the
                                       # template (qa-project and number filled in) for pass 1
$Q build interaction --check           # build.py on the latest source (--pass N for another), then check.py
$Q build interaction --all             # rebuild every page that has a source; keeps a page whose rebuild
                                       # fails check (old-format sources)
$Q place ~/somewhere/choices db-migration-v3/billing --create --title "Billing" --json
                                       # move passes made elsewhere in; leaves a symlink at the old place
$Q mkdir / mv / rename / icon / rmdir  # organise (the dashboard does the same: drag a tile onto a folder)
$Q serve --open                        # the dashboard: http://127.0.0.1:8750 (one origin: stars persist)
```

- One subject = one conversation thread (one qa-project), passes `QA-PASS-1`, `QA-PASS-2`, … in it. A
  new topic is a new subject; ask the user which folder it goes in when it is not obvious (`qap list`).
- Never write a pass outside the content root, and never into a code repo, unless the user asks. An old
  `<project>/choices/` path is a symlink into the content root now: it still works, but `qap where` gives
  the real path.
- The scripts stay usable directly (`~/.claude/skills/qa-pass/scripts/{carry,build,check}.py`); `qap`
  only picks the files for them.

## Page structure (in this order)

1. **Header.**
   - kicker `<PROJECT> · conversation, not a spec`;
   - `h1` `Q&A pass N — <topics>`;
   - a `sub` ("You answered … This file quotes you, answers you, and records what I think we now agree on");
   - `meta` (date, pass number, siblings, links to the PR, ticket or meeting notes).
2. **Lede.** The answer in one plain paragraph, numbers first.
3. **`mantras`.** "Where we are": one line per workstream.
4. **One section per subject, the core of the page.**
   - `h2 id="pN"` with `<span class="n">NN</span>` and **the conclusion as the title** ("SaT is two thirds
     of the time"), not the topic ("Timing"), in words the reader understands (see "Titles a reader
     understands").
   - One or more chips: `ok` agreed or done, `exp` explained, `rew` corrected (say what was wrong), `ask` needs
     the user. Chip text follows the same rule as titles.
   - **Every message is a `.msg` block with a stable id** `p<subject>-<pass><u|a>` (`u` the user, `a` the AI;
     pass `0` = the chat message that opened the subject, before pass 1), plus `data-pass`.
     - `<div class="msg user" id="p3-2u" data-pass="2"><div class="who">Me</div> … </div>`
     - `<div class="msg ai" id="p3-2a" data-pass="2"><div class="who">{{AI:claude|Claude|Opus 5.5}}</div> … </div>`
     - The AI message holds the **whole** answer: paragraphs, figures, tables, `pre` diagrams, cards, decision
       boxes. Nothing of the answer sits outside it, or the next pass cannot fold it.
   - `details.earlier` (closed, summary "Earlier in this thread"; the count is added for you): every earlier
     message **of this subject**, oldest first, **in its original formatting**. Options stay on their own lines
     (`ul.opts`), lists stay lists, and figures, tables and decision boxes stay visible when the fold opens.
     Never flatten an earlier message into one paragraph. For pass-0 chat messages, recover the original text
     from the transcript and keep its line breaks.
   - Then the user's **latest** words, verbatim, typos and line breaks included (`.msg.user`). Never paraphrase.
     When they answered a decision of this subject in the closing list, quote that answer here too.
   - Then your answer (`.msg.ai`): short sentences, numbers first, then the evidence.
   - A decision is a `.call.violet` box inside your answer: options with their consequence, and `Default: …`.
   - A ticket the user will create by hand: a `.ticket` card filled from their tracker's template (never create
     the ticket yourself; say where the template came from).
   - Optional material inside an answer (prefilled tickets, long tables) goes in a `details.more` fold, never in
     `details.earlier`, which is reserved for the thread's earlier messages.
5. **"What I need from you".** Every decision numbered (an `<ol>`; the build gives each item `id="need-N"`),
   with its default, plus one **answer line** (`ok` takes every default; otherwise for example
   `A1 · B go · C wait`).
6. A `.call.violet` **"What I will not do until you answer"**: no code, no prod write, no tickets, …
7. **Footer.** "Stored at `<path>` (the real path `qap where` gives). This is the conversation log for
   pass N, not the spec. Open it in a browser (or `qap serve`)."

The side table of contents builds itself from every `main h2[id]` and copies its chips. Every section needs
an `id`.

**Next pass on the same project:**
- Run `qap carry <subject>` (above; it runs `carry.py`). It moves each subject's open messages, byte for
  byte, into its fold, and adds `{{TODO:…}}` placeholders for the new round (the build refuses until they
  are filled or deleted).
- `--skip` the subjects the user did not answer: they keep their last round open.
- Keep the same subjects and ids. Settled subjects get an `ok` chip. New subjects go at the end, before the
  closing sections; renumber "What I need from you" to stay last (its id stays `need`).
- Rewrite the header, lede, "where we are" and closing sections by hand.

## Only what the reader can act on

The page is for decisions, surprises and understanding, not a work log. The user (Coach, 2026-10-25):
"I need you to present me with stuff that I can bring actual benefit from. … 'The proof of the rebuild,
every test suite pass' … That doesn't need a whole section. You can just say, 'all tests pass'."
- **Proof is one or two lines**, never a subject: "All suites pass (pgTAP, Python, edge, web, iOS,
  Android); 4 reviews, AUTHZ twice: 0 defects." Give a number only when it changes a decision.
- **No process narration**: which agent did what, the order you ran things, restores, CI waits, retries.
  If something went wrong and was fixed, one line, unless the user must know it to decide.
- **Spend the words on**: each decision and its consequence; findings that surprise (data that
  contradicts what the user believes, a security gap, a production risk); what changes for users and old
  clients; explanations the user asked for (with figures).
- **Test before writing a paragraph**: "Can the user decide, ask, or learn something from this that one line
  would not give?" If not, cut it to one line or drop it.

## Titles a reader understands

A section title is the first thing the reader sees, and the contents pane copies it word for word. It is for
the reader as much as for you.
- **The conclusion, in plain words** that make sense to someone who has not read the earlier passes and does
  not know the decision letters.
- **A decision code (A1, B1, C, D1, W2…) only with its meaning in the same title**: "dropping the Langfuse id
  column deletes real ids (D1)", never "D1 built".
- **A code name (function, table, column) only when the sentence still makes sense** to a reader who does not
  know it. Otherwise say what the thing does.
- **Longer is fine.** Clarity beats brevity.
- **Chips too**, since the contents pane copies them: "decision D" or "A1 implemented" says nothing;
  "Langfuse ids: D1 or D2?" does.

Two titles the user could not read, rewritten:
- ✗ "B1 built; C deferred with the retype re-proven on today's v3; D1 built, and it still deletes real Langfuse ids"
  ✓ "Comments, reviews and Serge threads now point at the session (`meeting_id` renamed `session_id` in 5
  tables); the 'onboarding' thread type waits for a production count; dropping the Langfuse id column deletes
  real ids"
- ✗ "J1 now means PRD-99's current names: mark_session_as_reviewed(p_session_id) and the rest keep their v3
  names; only create_meeting_thread_with_opener still says meeting"
  ✓ "The apps keep calling every function by the name it has today (PRD-99 already renamed the 'meeting'
  ones to 'session'); only the one that opens a Serge thread with its first message still says 'meeting'"

`check.py` warns when a title or a chip uses a decision code with no meaning next to it.

## Every reference is a link

The page is long. "§ 4" or "subject 14" without a link sends the reader searching 10,000 words.
- **In the page** (subject NN, need item N, a decision box, an earlier message): a link to its anchor.
  `build.py` links "subject 05", "subjects 09 and 20", "subjects 04–14" and "need item 12" for you, when the
  target exists (never inside `code`, `pre`, links or chips). In a message of an earlier pass (a fold, a
  skipped subject's open round), "need item N" means that pass's list, so it links to `QA-PASS-K.html#need-N`:
  pass K for the AI's message of pass K, pass K-1 for the user's (their reply to, and quotes of, pass K-1).
  Link anything else yourself: give a decision box an `id` and write
  `<a href="#dec-d">decision D, the Langfuse ids</a>`; a link into a closed fold opens it.
- **In a repo doc or code:** link the exact place, and name the section in words: "name map § 4,
  'Constraints, indexes, triggers and policies'", not "name map, § 4".
  - A GitHub blob URL pinned at a commit SHA, never a branch (lines move):
    `https://github.com/<org>/<repo>/blob/<sha>/backend/ai/x.py#L72` (or `#L72-L80`).
  - Markdown renders on GitHub, so use `?plain=1#L165`, or the heading's anchor
    (`#4-constraints-indexes-triggers-and-policies`).
  - Not on GitHub (a local file, an unpushed branch): a `file://` link, or quote the excerpt in a
    `details.more` fold right there.
- **Never a bare "§ 4" or `file.py:72`.** `check.py` warns on those, and fails on a `#link` whose id does
  not exist.

## Graphs, plots and pictures: use them

A QA pass is read by someone deciding. A good chart decides faster than three paragraphs of percentages.
**Whenever an answer carries numbers, ask whether a figure would carry them better. Usually it would.**
- **Breakdowns** (time, cost or errors per stage, by size bucket): stacked bars.
- **Each item against a limit** (per-meeting duration vs words, with the 30-min line): a scatter with dashed
  threshold lines, coloured by outcome.
- **Before / after, or raw vs adjusted, per arm:** grouped bars with value labels.
- **Trends** (per day or week): a line chart with averages drawn as reference lines.
- **Distributions** (counts per meeting, grades): histograms or box plots.
- **Mechanisms** (a retry loop, a pipeline): a plain-English `pre` timeline (`0 min … 30 min …`), or a
  small SVG.
- **UI:** real screenshots (the `headless-screenshots` skill, or the Playwright MCP), never mock-ups
  presented as real.
- **Series figures.** When passes come in a series (one per family, ticket or module), every pass carries
  the figure that puts this item among its siblings, with current numbers, in an open answer (not only in a
  fold). For the v3 families: how many function bodies, keys, RPCs, GraphQL operations and clients each move
  touched. Copy the last sibling's script, add this item, redraw. Examples:
  `db-migration-v3/system-org/img/org-vs-system.py`, `db-migration-v3/signal/img/family-size.py`,
  `db-migration-v3/session/img/family-size.py` (in the content root).

**How to draw them**
- Use `scripts/chart_style.py` (matplotlib) with `uv run --no-project --with matplotlib python chart.py`.
  Nothing needs installing.
- **The title states the conclusion.** Axes carry units. Annotate the points that make the argument.
- **Colour encodes a verdict** (pass/fail, better/worse), not a value. Draw limits and gates as labelled
  dashed lines. Put the legend below the plot when it would hide data.
- Every figure gets a `figcaption`: what to read, the source, the time window, and `n`.
- Charts are saved at 200 dpi (`chart_style.py`), so they stay sharp on 2× screens and in the wide
  figure column of large monitors.
- **Look at every PNG before you embed it** (open the image), and fix overlaps and unreadable labels. A
  chart that misleads is worse than none.
- Keep the script that made each chart next to the PNG in `img/`, so the next pass can redraw it.

## Writing rules

- Plain short sentences, numbers first, one idea per bullet. Lead with the answer, then the evidence.
- Quote the user verbatim. Quote yourself as you wrote it in `details.earlier`.
- Say what you got wrong, plainly, with a `rew` chip and the corrected number.
- Mark anything you did not verify as unverified. Never round a guess into a fact.
- Write in the language the user uses for the project's passes (English for Coach so far); keep their quotes
  as they wrote them.
- Defaults are real recommendations. A prod write, a config change or anything outward-facing needs an
  explicit yes: its default is "no, until you say so".

## Before you hand it over

1. `qap build <subject> --check` (build.py, then check.py), with no PROBLEM line. Read every warning; fix every title, chip and
   reference warning in the open sections (earlier folds stay as written).
2. **Render check.**
   - The Playwright MCP blocks `file:` URLs, so serve the content: `qap serve --port 8765 --json` (in the
     background; it prints the URL). Open a NEW tab on
     `http://127.0.0.1:8765/#/<subject>?pass=N` (the dashboard) or `http://127.0.0.1:8765/c/<subject>/QA-PASS-N.html`
     (the page alone), and take screenshots of the top, one subject and the decisions.
   - Check both themes (click `#theme-toggle`); that the article does not move when `#toc-toggle` opens or
     closes the pane (compare `main.getBoundingClientRect().left`); star two messages, one in a fold, open
     `#stars-open`, and click a row: the fold opens and the message flashes. Then unstar those two. Click one
     "subject NN" link and one link into a fold; the "↩ Back to …" button appears right of Contents and returns
     to the link.
   - **Never clear `localStorage` in a render check.** The Playwright browser can be the user's own profile:
     its storage holds their stars and theme. Undo only what the check itself set.
   - Browsers cache the page: add `?v=N` to the URL after each rebuild.
   - Check one wide viewport (for example 3440×1300) and one narrow one (760 px).
   - Stop the server afterwards and close the tab.
   - If Playwright is not connected, say so (see the rule at the top) and check the HTML by reading it.
3. **In the chat:**
   - the path;
   - a three-to-five-line summary of what changed;
   - the decisions with their defaults;
   - the answer line;
   - any connection that was missing.

   Don't paste the whole page into the chat.
