// build-log in the dashboard: a "log" item in the top bar, a view listing the entries, a command in the ⧉ menu.
export function onload(app) {
  const { el } = app;
  const open = () => { location.hash = app.viewHref("log"); };
  app.addStatusItem({ text: "log", title: "Build log (example plugin)", onclick: open });
  app.addCommand({ id: "open", name: "Build log: open", run: open });
  app.registerView("log", {
    title: "Build log",
    async render(box) {
      const r = await app.request("entries?n=100");
      const rows = (r.entries || []).reverse().map((e) =>
        el("li", {}, el("code", { text: e.at.replace("T", " ") }), ` ${e.event} · ${e.what}${e.ok ? "" : " (failed)"}`));
      box.replaceChildren(el("h1", { text: "Build log" }),
        rows.length ? el("ol", { class: "plugin-commands" }, ...rows) : el("p", { class: "empty", text: "Nothing logged yet." }));
    },
  });
}

export function onunload() {
  // everything added through `app` is removed by qap; free here anything else you set up yourself
}
