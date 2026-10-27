// git-storage in the dashboard: a pill in the top bar (backed up? changes waiting? a conflict?) and a
// "Git backup" view (#/~plugins/git-storage/status) to set it up, sync now, settle a conflict and read the
// latest commits. Everything goes through the plugin's Python side: GET status, and its commands (run).

function ago(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleString();
}

export function onload(app) {
  const { el, toast, dialog } = app;
  let status = null;
  let busy = false;

  const pill = app.addStatusItem({ title: "Git backup", onclick: () => { location.hash = app.viewHref("status"); } });
  pill.classList.add("git-pill");

  function describe(s) {
    if (!s || s.ok === false) return { state: "error", text: "git ?", title: s?.error || "status unavailable" };
    if (!s.initialized) return { state: "off", text: "git off", title: "Not backed up with git: click to set it up" };
    if (s.conflict) return { state: "bad", text: "git ⚠ conflict", title: `Conflict with ${s.conflict.ref}: automatic syncs are paused` };
    if (s.in_progress) return { state: "bad", text: `git ⚠ ${s.in_progress}`, title: `A ${s.in_progress} is in progress in the content root` };
    if (s.last_error) return { state: "bad", text: "git ⚠", title: `Last sync failed: ${s.last_error.error}` };
    const last = s.last_sync ? `last sync ${ago(s.last_sync.at)}` : "never synced";
    if (s.changed || s.ahead) {
      const what = s.changed ? `${s.changed} changed` : `${s.ahead} to push`;
      return { state: "pending", text: `git ● ${what}`, title: `${s.changed} uncommitted change(s), ${s.ahead || 0} commit(s) to push; ${last}` };
    }
    return { state: "ok", text: "git ✓", title: `Backed up; ${last}` };
  }

  function paint() {
    const d = describe(status);
    pill.dataset.state = busy ? "busy" : d.state;
    pill.textContent = busy ? "git …" : d.text;
    pill.title = d.title;
  }

  async function poll() {
    status = await app.request("status");
    paint();
  }

  async function syncNow() {
    if (busy) return;
    busy = true;
    paint();
    const r = await app.run("sync");
    busy = false;
    toast(r.text || r.error || "done", { error: !r.ok, ms: r.ok ? 5000 : 15000 });
    await poll();
    app.refresh(); // passes pulled from another machine show up, and an open Git backup view redraws
  }

  app.addCommand({ id: "sync", name: "Git: commit and sync now", run: syncNow });
  app.addCommand({ id: "status", name: "Git: backup status", run: () => { location.hash = app.viewHref("status"); } });
  app.registerView("status", { title: "Git backup", render: renderView });
  app.on("tree", poll);              // after a move, a rename, a new folder…
  app.registerInterval(poll, 30000);
  poll();

  // ---- the view ----
  async function renderView(box, tools) {
    status = await app.request("status");
    paint();
    const s = status;
    box.classList.add("git-view");
    const head = el("h1", { text: "Git backup" });
    if (!s.ok) { box.replaceChildren(head, el("p", { class: "empty", text: s.error })); return; }
    if (!s.initialized) { box.replaceChildren(head, setupForm(s)); return; }
    tools.replaceChildren(el("button", { class: "btn primary", type: "button", text: "Sync now", onclick: syncNow }));
    const parts = [head, el("p", { class: "lede" }, el("code", { text: s.remote.url || "no remote" }), ` · branch ${s.branch}`)];
    if (s.conflict) parts.push(conflictBox(s.conflict));
    if (s.in_progress) parts.push(el("div", { class: "git-box bad" },
      el("p", { text: `A ${s.in_progress} is in progress in ${s.root}. Finish it (or git ${s.in_progress} --abort) and sync again.` })));
    if (s.last_error && !s.conflict) parts.push(el("div", { class: "git-box bad" },
      el("h2", { text: `Last sync failed (${ago(s.last_error.at)})` }), el("pre", { class: "git-out", text: s.last_error.error })));
    const last = s.last_sync;
    const auto = s.auto || {};
    parts.push(el("dl", { class: "git-facts" },
      el("dt", { text: "Last sync" }), el("dd", { text: last ? `${ago(last.at)} (${last.trigger}) at ${last.commit || "—"}` : "never" }),
      el("dt", { text: "Uncommitted" }), el("dd", { text: String(s.changed) }),
      el("dt", { text: "To push" }), el("dd", { text: s.upstream ? String(s.ahead) : "everything (never pushed)" }),
      el("dt", { text: "To pull" }), el("dd", { text: s.upstream ? `${s.behind} (as of the last fetch)` : "—" }),
      el("dt", { text: "Automatic" }), el("dd", {},
        [auto.interval_minutes ? `every ${auto.interval_minutes} min while qap serve runs` : "no interval",
         auto.after_build ? "after each build" : null, auto.on_startup ? "when qap serve starts" : null,
         auto.push === false ? "push off" : null].filter(Boolean).join(" · "), " · ",
        el("a", { href: "#/~plugins", text: "settings" }))));
    if (s.warnings.length) parts.push(el("ul", { class: "git-warnings" }, ...s.warnings.map((w) => el("li", { text: w }))));
    if (s.changes.length) {
      parts.push(el("h2", { text: "Not committed yet" }),
        el("ul", { class: "git-files" }, ...s.changes.slice(0, 50).map((c) =>
          el("li", {}, el("b", { text: c.status }), el("code", { text: c.path })))));
    }
    if (s.recent.length) {
      parts.push(el("h2", { text: "Latest commits" }),
        el("ol", { class: "git-log" }, ...s.recent.map((c) =>
          el("li", {}, el("code", { text: c.sha }), el("span", { text: c.subject }),
            el("small", { text: `${ago(c.date)} · ${c.files} file${c.files === 1 ? "" : "s"}` })))));
    }
    box.replaceChildren(...parts);
  }

  function setupForm(s) {
    const url = el("input", { type: "text", placeholder: "git@github.com:you/qa-passes.git   or   file:///path/to/backup.git" });
    const branch = el("input", { type: "text", value: "main" });
    const out = el("pre", { class: "git-out", hidden: true });
    const go = el("button", { class: "btn primary", type: "button", text: "Set up and sync" });
    go.addEventListener("click", async () => {
      go.disabled = true;
      out.hidden = false;
      out.textContent = "Working…";
      const r = await app.run("init", { remote: url.value.trim(), branch: branch.value.trim() || "main" });
      go.disabled = false;
      out.textContent = r.text || r.error;
      if (r.ok) { toast("Backed up with git"); await poll(); app.refresh(); }
    });
    return el("div", { class: "git-setup" },
      el("p", { text: "Not backed up yet. qap can keep this whole content root (projects, folders, subjects, passes and their " +
        "images) in a git repository you own, and sync it after each build, every few minutes while the dashboard runs, and when it starts." }),
      el("p", { text: "Use an empty private repository, or a file:// path to a bare one. Credentials stay with git (your ssh agent " +
        "or credential helper); qap never stores one. Into an empty content root, the same command restores an existing backup." }),
      el("label", {}, el("span", { text: "Remote URL" }), url),
      el("label", {}, el("span", { text: "Branch" }), branch),
      el("div", {}, go), out,
      s.parent_repo ? el("p", { class: "help", text: `This folder sits inside the git repository ${s.parent_repo}; qap makes a ` +
        "separate repository here and never touches that one." }) : null);
  }

  function conflictBox(c) {
    const keep = (side) => async () => {
      const files = c.files.slice(0, 5).join(", ") + (c.files.length > 5 ? ` and ${c.files.length - 5} more` : "");
      const sure = await dialog(side === "mine" ? "Keep this machine's version?" : "Keep the remote's version?", (body) => {
        body.append(el("p", { text: `For ${files}. The other version stays in the history ` +
          `(commit ${side === "mine" ? c.theirs : c.mine}).` }));
        return () => true;
      }, side === "mine" ? "Keep mine" : "Keep theirs");
      if (!sure) return;
      busy = true;
      paint();
      const r = await app.run("resolve", { keep: side });
      busy = false;
      toast(r.text || r.error, { error: !r.ok, ms: 12000 });
      await poll();
      app.refresh();
    };
    return el("div", { class: "git-box bad" },
      el("h2", { text: "Conflict: automatic syncs are paused" }),
      el("p", { text: `This machine and ${c.ref} both changed these files (${ago(c.at)}, during a ${c.trigger} sync). ` +
        "Nothing was pushed and your files are as they were: the merge was undone." }),
      el("ul", { class: "git-files" }, ...c.files.slice(0, 20).map((f) => el("li", {}, el("code", { text: f })))),
      el("div", { class: "row" },
        el("button", { class: "btn", type: "button", text: "Keep mine", onclick: keep("mine") }),
        el("button", { class: "btn", type: "button", text: "Keep theirs", onclick: keep("theirs") })),
      el("p", { class: "help" }, "Or merge by hand in ", el("code", { text: status.root }), ": ",
        el("code", { text: `git merge ${c.ref}` }), ", fix, commit, then Sync now."));
  }
}
