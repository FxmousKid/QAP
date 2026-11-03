// Share, on the pass bar: download the page, or run the command saved on this machine.
// The download and the file the command receives are copies. A home directory in them is ~/.
// The command is not in the page. The server reads it from the config file.
import { api } from "./api.js";
import { el, menu, dialog, toast } from "./dialogs.js";

let sending = false;

export function shareButton(node, pass) {
  return el("button", {
    class: "btn share", type: "button", text: "Share",
    title: "Download this pass, or send it with the saved command",
    "aria-haspopup": "menu", "aria-expanded": "false",
    onclick: (e) => { e.stopPropagation(); openMenu(e.currentTarget, node, pass); },
  });
}

function openMenu(anchor, node, pass) {
  menu(anchor, [
    { label: "Download HTML", run: () => download(node, pass) },
    { label: "Send", run: () => send(node, pass) },
  ]);
}

function relOf(node, pass) {
  return [node.path, pass.file].filter(Boolean).join("/");
}

// The server names the file after the subject and the title. filename* carries that name.
function downloadName(res, fallback) {
  const disp = res.headers.get("Content-Disposition") || "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disp);
  if (star) {
    try { return decodeURIComponent(star[1].trim()); } catch (e) { /* the plain name below */ }
  }
  const plain = /filename="([^"]*)"/.exec(disp);
  return (plain && plain[1]) || fallback || "QA-PASS.html";
}

async function download(node, pass) {
  const rel = relOf(node, pass);
  let res;
  try {
    res = await fetch("/api/share/file?path=" + encodeURIComponent(rel));
  } catch (e) {
    toast("Could not download the pass", { error: true });
    return;
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try { message = (await res.json()).error || message; } catch (e) { /* the body is the page */ }
    toast(message, { error: true });
    return;
  }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = downloadName(res, pass.file);
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
}

async function send(node, pass) {
  if (sending) return;
  const rel = relOf(node, pass);
  let info;
  try {
    info = await api.shareInfo(rel);
  } catch (e) {
    toast(e.message, { error: true });
    return;
  }
  const ready = !!(info.command || "").trim();
  const go = await dialog(ready ? "Send this pass" : "Share command", (body) => {
    body.append(
      el("p", { class: "hint", text: ready
        ? "The template is the one in the config. Each value is in double quotes. The copy's directory is chosen when you send, and a home directory in the copy is ~."
        : "Set the template on this machine. The page keeps no command of its own." }),
      el("pre", { class: "share-preview", text: ready
        ? info.preview
        : "qap config share_command '" + info.suggested + "'" }));
    return () => true;
  }, ready ? "Send" : null, "wide");
  if (!ready || go !== true) return;
  sending = true;
  toast("Sending…", { ms: 90000 });
  try {
    const data = await api.shareRun(rel);
    if (data.url) {
      toast(data.url, {
        ms: 20000,
        action: { label: "Copy", run: () => navigator.clipboard.writeText(data.url) },
      });
    } else {
      toast((data.stdout || "Sent").trim().slice(-180) || "Sent");
    }
  } catch (e) {
    toast(e.message, { error: true, ms: 12000 });
  } finally {
    sending = false;
  }
}
