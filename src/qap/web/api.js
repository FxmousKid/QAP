// The server's JSON API. Every write goes through qap.layout on the server, the same code as the CLI.

async function call(path, body) {
  const init = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, init);
  let data;
  try { data = await res.json(); } catch (e) { data = { ok: false, error: `HTTP ${res.status}` }; }
  if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// A project is "@<id>" wherever a path goes: mkdir("@work", …) makes a top-level folder in it, mv(x, "@work") puts x
// in it, rename / icon / rmdir("@work") change or delete it.
export const api = {
  tree: () => call("/api/tree"),
  mkdir: (parent, title, icon, color) => call("/api/mkdir", { parent, title, icon, color }),
  project: (title, icon, color) => call("/api/project", { title, icon, color }),
  mv: (src, dest) => call("/api/mv", { src, dest }),
  rename: (path, title) => call("/api/rename", { path, title }),
  icon: (path, icon, color) => call("/api/icon", { path, icon, color }),
  rmdir: (path) => call("/api/rmdir", { path }),
};

// A page of the content, as the server serves it.
export function contentUrl(subjectPath, file) {
  const parts = (subjectPath ? subjectPath.split("/") : []).concat(file ? [file] : []);
  return "/c/" + parts.map(encodeURIComponent).join("/");
}
