// QA pass page behaviour: theme toggle, the contents pane (fixed, never pushes the article) with scroll-spy,
// screen detection (pixel ratio, width tier, ultrawide), message labels (pass + star on every message) and
// the "View ★s" dialog, a reference list of starred messages, and the "back to where I clicked" button.
// The theme, the pane state and the pixel ratio are first applied before paint by the inline boot snippet in
// <head> (THEME_BOOT in build.py); this file keeps them up to date.
(function () {
  var root = document.documentElement;
  var STAR_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l2.75 5.57 6.15.9-4.45 4.33 1.05 6.12L12 16.84l-5.5 2.89 1.05-6.12L3.1 9.27l6.15-.9z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';

  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function meta(name) { var m = document.querySelector('meta[name="' + name + '"]'); return m ? m.content : ""; }
  function narrow() { return window.innerWidth <= 1000; }

  // ---- theme ----
  function setTheme(theme) {
    root.dataset.theme = theme;
    store("qa-theme", theme);
    var button = document.getElementById("theme-toggle");
    if (button) button.textContent = theme === "dark" ? "☀ Light" : "☾ Dark";
    placeBack();  // the toggle's width changes with its label
  }

  // ---- contents pane (fixed; the article reserves its gutter, so opening it moves nothing) ----
  function setToc(open, remember) {
    root.classList.toggle("toc-open", open);
    var button = document.getElementById("toc-toggle");
    if (button) button.setAttribute("aria-expanded", open ? "true" : "false");
    if (remember && !narrow()) store("qa-toc", open ? "open" : "closed");
  }

  // ---- screen detection ----
  function sizeTier(width) {
    if (width >= 3000) return "xxl";
    if (width >= 2400) return "xl";
    if (width >= 1900) return "l";
    if (width >= 1500) return "m";
    if (width >= 1000) return "s";
    return "xs";
  }

  function detectScreen() {
    var dpr = window.devicePixelRatio || 1;
    var w = window.innerWidth;
    var sw = window.screen ? screen.width : w;
    var sh = window.screen ? screen.height : window.innerHeight;
    root.dataset.dpr = dpr >= 2.5 ? "3" : dpr >= 1.5 ? "2" : "1";
    root.dataset.size = sizeTier(w);
    root.dataset.ultrawide = sw / Math.max(1, sh) >= 2.1 ? "1" : "0";
    var env = document.getElementById("env");
    if (env) {
      env.textContent = "Rendering for: screen " + sw + "×" + sh + " · window " + w + "×" + window.innerHeight +
        " · pixel ratio " + Math.round(dpr * 100) / 100 + " · layout " + root.dataset.size +
        (root.dataset.ultrawide === "1" ? " · ultrawide" : "");
    }
    var stars = document.getElementById("stars-open");
    if (stars) root.style.setProperty("--stars-w", stars.offsetWidth + "px");
    placeBack();  // the top row's buttons moved (window width, star count): the back button's room follows
  }

  function watchPixelRatio() {
    // Fires when the page moves to a screen with another pixel ratio, or on browser zoom.
    if (!window.matchMedia) return;
    var mq = window.matchMedia("(resolution: " + (window.devicePixelRatio || 1) + "dppx)");
    var onChange = function () { detectScreen(); watchPixelRatio(); };
    if (mq.addEventListener) mq.addEventListener("change", onChange, { once: true });
    else if (mq.addListener) mq.addListener(onChange);
  }

  // ---- table of contents ----
  function h2Title(h2) {
    return Array.prototype.filter.call(h2.childNodes, function (n) {
      return !(n.nodeType === 1 && n.classList.contains("n"));
    }).map(function (n) { return n.textContent; }).join("").trim();
  }

  function buildToc() {
    var list = document.getElementById("toc-list");
    if (!list) return [];
    var links = [];
    document.querySelectorAll("main h2[id]").forEach(function (h2) {
      var a = document.createElement("a");
      a.href = "#" + h2.id;
      var num = h2.querySelector(".n");
      if (num) {
        var tn = document.createElement("span");
        tn.className = "tn";
        tn.textContent = num.textContent;
        a.appendChild(tn);
      }
      a.appendChild(document.createTextNode(h2Title(h2)));
      var sib = h2.nextElementSibling;
      var chips = [];
      while (sib && sib.classList && sib.classList.contains("chip")) { chips.push(sib); sib = sib.nextElementSibling; }
      if (chips.length) {
        a.appendChild(document.createElement("br"));
        chips.forEach(function (c) { a.appendChild(c.cloneNode(true)); });
      }
      a.addEventListener("click", function () { if (narrow()) setToc(false, false); });
      var li = document.createElement("li");
      li.appendChild(a);
      list.appendChild(li);
      links.push({ a: a, target: h2 });
    });
    return links;
  }

  function spy(links) {
    if (!links.length) return;
    function update() {
      var current = links[0];
      var offset = window.innerHeight * 0.25;
      links.forEach(function (l) { if (l.target.getBoundingClientRect().top - offset <= 0) current = l; });
      links.forEach(function (l) { l.a.classList.toggle("active", l === current); });
    }
    window.addEventListener("scroll", update, { passive: true });
    update();
  }

  // ---- messages: pass label + star on every .msg ----
  var messages = [];   // [{el, id, subject, num, kind, pass, excerpt, label}]
  var project = meta("qa-project") || document.title.split(" — ")[0] || "qa-pass";
  var STORE_KEY = "qa-stars:" + project;

  function passOf(el) {
    var p = el.getAttribute("data-pass");
    if (p === null) { var m = /-(\d+)[ua]$/.exec(el.id || ""); p = m ? m[1] : ""; }
    return p;
  }
  function passLabel(p) { return p === "" ? "" : p === "0" ? "chat, before pass 1" : "pass " + p; }

  function excerptOf(el) {
    var clone = el.cloneNode(true);
    clone.querySelectorAll(".who, figure, pre, table, .chip").forEach(function (n) { n.remove(); });
    // Block elements end with a space, so "fix 2" + "The safety net" does not read "fix 2The safety net".
    clone.querySelectorAll("p, li, div, h3, h4, h5, td, th, summary, br, .sk").forEach(function (n) {
      n.appendChild(document.createTextNode(" "));
    });
    var text = clone.textContent.replace(/\s+/g, " ").trim();
    if (text.length <= 140) return text;
    var cut = text.slice(0, 140);
    var space = cut.lastIndexOf(" ");
    return (space > 90 ? cut.slice(0, space) : cut) + " …";
  }

  // Whether this page can keep stars: some viewers give every file its own storage (or none), so
  // stars made in one pass never reach the next. The dialog says so instead of looking empty.
  function storageState() {
    var origin = location.origin || "null";
    try {
      localStorage.setItem("qa-probe", "1");
      var ok = localStorage.getItem("qa-probe") === "1";
      localStorage.removeItem("qa-probe");
      return { ok: ok && origin !== "null", origin: origin };
    } catch (e) { return { ok: false, origin: origin }; }
  }

  // The ids a carry.py --stars seed wrote into this pass: added once to the stars, so an unstar sticks.
  function applySeed() {
    var seed = meta("qa-stars-seed");
    if (!seed) return;
    var done = STORE_KEY + ":seed:" + seed;
    if (load(done)) return;
    var stars = readStars();
    seed.split(",").forEach(function (id) {
      if (!id || stars[id]) return;
      var m = messages.filter(function (x) { return x.id === id; })[0];
      stars[id] = m ? { n: m.num, s: m.subject, k: m.kind, l: m.labelText, h: m.labelHtml, p: m.pass, x: m.excerpt, t: Date.now() }
                    : { t: Date.now() };
    });
    writeStars(stars);
    store(done, "1");
  }

  function readStars() {
    try { return JSON.parse(load(STORE_KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function writeStars(stars) { store(STORE_KEY, JSON.stringify(stars)); }

  function indexMessages() {
    var subject = { num: "", title: "" };
    document.querySelectorAll("main h2[id], main .msg").forEach(function (el) {
      if (el.tagName === "H2") {
        var n = el.querySelector(".n");
        subject = { num: n ? n.textContent.trim() : "", title: h2Title(el), id: el.id };
        return;
      }
      if (!el.id) return;
      var who = el.querySelector(":scope > .who");
      var kind = el.classList.contains("user") ? "user" : "ai";
      var p = passOf(el);
      var aiLabel = who ? who.querySelector(".ai-label") : null;
      messages.push({ el: el, id: el.id, num: subject.num, subject: subject.title, kind: kind, pass: p,
        excerpt: excerptOf(el), labelHtml: aiLabel ? aiLabel.outerHTML : "",
        labelText: kind === "user" ? "Me" : (aiLabel ? aiLabel.textContent.replace(/\s+/g, " ").trim() : "AI") });
      if (who) {
        // Bare text in the label ("Me") gets its own span, so the line itself keeps the body font.
        Array.prototype.slice.call(who.childNodes).forEach(function (n) {
          if (n.nodeType === 3 && n.textContent.trim()) {
            var me = document.createElement("span");
            me.className = "me";
            me.textContent = n.textContent.trim();
            who.replaceChild(me, n);
          }
        });
        if (p !== "" && !who.querySelector(".pass")) {
          var ps = document.createElement("span");
          ps.className = "pass";
          ps.textContent = "· " + passLabel(p);
          who.appendChild(ps);
        }
        var star = document.createElement("button");
        star.type = "button";
        star.className = "star";
        star.innerHTML = STAR_SVG;
        star.setAttribute("data-id", el.id);
        who.appendChild(star);
      }
    });
  }

  function paintStars() {
    var stars = readStars();
    document.querySelectorAll(".star[data-id]").forEach(function (b) {
      var on = !!stars[b.getAttribute("data-id")];
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.title = on ? "Unstar this message" : "Star this message";
      b.setAttribute("aria-label", b.title);
    });
    var count = document.querySelector("#stars-open .count");
    if (count) {
      var n = Object.keys(stars).length;
      count.textContent = n ? String(n) : "";
    }
    detectScreen();
  }

  function toggleStar(id) {
    var stars = readStars();
    if (stars[id]) delete stars[id];
    else {
      var m = messages.filter(function (x) { return x.id === id; })[0];
      stars[id] = m ? { n: m.num, s: m.subject, k: m.kind, l: m.labelText, h: m.labelHtml, p: m.pass, x: m.excerpt, t: Date.now() }
                    : { t: Date.now() };
    }
    writeStars(stars);
    paintStars();
  }

  // ---- go to a message or any anchor (subject, need item, decision box): unfold its folds, scroll, flash ----
  // push: true for a link the reader clicked, so the browser's Back returns to the sentence they were reading.
  function goTo(id, push) {
    var el = document.getElementById(id);
    if (!el) return false;
    // Pushed before the jump, so the entry the reader leaves keeps the place they clicked from. The state
    // carries the depth of the back-to-link stack (origins recorded so far, this jump's included), so the
    // browser's Back and the button stay in step.
    if (push && history.pushState) history.pushState({ qaj: origins.length }, "", "#" + id);
    for (var p = el.parentElement; p; p = p.parentElement) { if (p.tagName === "DETAILS") p.open = true; }
    el.scrollIntoView({ behavior: "instant", block: "start" });
    window.scrollBy(0, -60);
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
    if (!push && history.replaceState) history.replaceState(null, "", "#" + id);
    return true;
  }

  function inClosedFold(el) {
    for (var p = el.parentElement; p; p = p.parentElement) { if (p.tagName === "DETAILS" && !p.open) return true; }
    return false;
  }

  // ---- "back to where I clicked" ----
  // A jump through an in-page link (or a row of the stars dialog) records where the reader was: the link
  // itself and its height on the screen. A small, faint button then shows in the top row, right of
  // ☰ Contents ("↩ Back to subject 05", "↩ Back to What I need from you"). It returns to the link,
  // opening the folds around it if they were closed, and flashes it. Jumps stack: after one return the
  // button offers the previous origin, until none is left. It fades out by itself 20 s after the last jump
  // (hovering it keeps it), and comes back with the next jump. Each jump is a history entry, so the
  // browser's Back does the same thing. Key: b.
  var BACK_MS = 20000;
  var origins = [];          // [{el, top, y}], oldest first
  var backTimer = 0;
  var restoringUntil = 0;    // the hashchange that follows a return must not jump again

  function backButton() {
    var b = document.getElementById("back-to-link");
    if (b) return b;
    b = document.createElement("button");
    b.type = "button";
    b.id = "back-to-link";
    b.hidden = true;
    b.innerHTML = '<span class="bk-arrow" aria-hidden="true">↩</span><span class="bk-text"></span><span class="bk-more"></span>';
    b.addEventListener("click", goBack);
    b.addEventListener("mouseenter", function () { clearTimeout(backTimer); b.classList.remove("fading"); });
    b.addEventListener("mouseleave", function () { if (!b.hidden) armBack(); });
    document.body.appendChild(b);
    return b;
  }

  function placeBack() {
    // Docked in the top row, right of ☰ Contents, in the room before the theme toggle, on every layout: it
    // never covers the header or the line a jump lands on (60 px down). With little room it keeps only its
    // arrow ("+N" becomes a corner badge; the full label stays in its tooltip and aria-label); with none (the
    // smallest phones) it moves to the bottom left corner.
    var toc = document.getElementById("toc-toggle");
    var theme = document.getElementById("theme-toggle");
    var b = document.getElementById("back-to-link");
    var left = toc ? toc.getBoundingClientRect().right + 8 : 16;
    var room = Math.floor((theme ? theme.getBoundingClientRect().left - 8 : window.innerWidth - 16) - left);
    root.style.setProperty("--back-left", Math.round(left) + "px");
    root.style.setProperty("--back-room", Math.max(0, room) + "px");
    if (b) {
      b.classList.toggle("compact", room < 96);
      b.classList.toggle("low", room < 30);
    }
  }

  function whereIs(el) {
    // "subject 05", or the title of the section the origin sits in.
    var h = null;
    document.querySelectorAll("main h2[id]").forEach(function (h2) {
      if (h2 === el || (h2.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) h = h2;
    });
    if (!h) return "the top";
    var n = h.querySelector(".n");
    if (n && /^p\d+$/.test(h.id)) return "subject " + n.textContent.trim();
    var t = h2Title(h);
    return t.length > 32 ? t.slice(0, 30) + "…" : t;
  }

  function readingSpot() {
    // No link was clicked (a row of the stars dialog): remember the block at the top of the reading area.
    var main = document.querySelector("main");
    var x = main ? main.getBoundingClientRect().left + 60 : 80;
    var hit = document.elementFromPoint(x, Math.min(window.innerHeight - 1, 110));
    return hit && hit.closest ? hit.closest("p, li, h2, h3, .msg, figure, pre, table, .call, header") : null;
  }

  function recordOrigin(el) {
    el = el || readingSpot();
    origins.push({ el: el, top: el ? el.getBoundingClientRect().top : 0, y: window.scrollY });
    if (origins.length > 30) origins.shift();
    showBack();
  }

  function showBack() {
    if (!origins.length) return hideBack();
    var b = backButton();
    var o = origins[origins.length - 1];
    var label = "Back to " + (o.el ? whereIs(o.el) : "where you were");
    var more = origins.length > 1 ? "; " + (origins.length - 1) + " more jump(s) before it" : "";
    b.querySelector(".bk-text").textContent = label;
    b.querySelector(".bk-more").textContent = origins.length > 1 ? "+" + (origins.length - 1) : "";
    // The label also lives in the tooltip and the accessible name: a narrow window shows only the arrow.
    b.title = label + ": return to the link you clicked (b)" + more;
    b.setAttribute("aria-label", label + more);
    placeBack();
    b.hidden = false;
    b.classList.remove("fading");
    armBack();
  }

  function armBack() {
    clearTimeout(backTimer);
    backTimer = setTimeout(function () {
      var b = document.getElementById("back-to-link");
      if (!b) return;
      b.classList.add("fading");
      backTimer = setTimeout(function () { b.hidden = true; b.classList.remove("fading"); }, 600);
    }, BACK_MS);
  }

  function hideBack() {
    clearTimeout(backTimer);
    var b = document.getElementById("back-to-link");
    if (b) { b.hidden = true; b.classList.remove("fading"); }
  }

  function restore(o) {
    if (!o) return;
    restoringUntil = Date.now() + 400;
    var el = o.el && o.el.isConnected ? o.el : null;
    if (el) {
      for (var p = el.parentElement; p; p = p.parentElement) { if (p.tagName === "DETAILS") p.open = true; }
      window.scrollBy({ top: el.getBoundingClientRect().top - o.top, behavior: "instant" });
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
      if (el.focus && el.tagName === "A") el.focus({ preventScroll: true });
    } else {
      window.scrollTo({ top: o.y, behavior: "instant" });
    }
    if (origins.length) showBack(); else hideBack();
  }

  function goBack() {
    if (!origins.length) return hideBack();
    // At the entry our last jump made: let history go back too, so Back and Forward stay meaningful.
    if (history.state && history.state.qaj === origins.length && history.back) { history.back(); return; }
    restore(origins.pop());
  }

  window.addEventListener("popstate", function (e) {
    var depth = e.state && typeof e.state.qaj === "number" ? e.state.qaj : 0;
    if (depth >= origins.length) return;          // Forward, or an entry that is not ours
    var o = null;
    while (origins.length > depth) o = origins.pop();
    // After the browser's own scroll restoration, which runs after popstate.
    setTimeout(function () { restore(o); }, 0);
  });

  // ---- the "View ★s" dialog: a reference list, never the full messages ----
  function buildDialog() {
    var dlg = document.getElementById("stars-dialog");
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.id = "stars-dialog";
      document.body.appendChild(dlg);
    }
    dlg.setAttribute("aria-label", "Starred messages");
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
    return dlg;
  }

  function renderDialog(dlg) {
    var stars = readStars();
    var ids = Object.keys(stars);
    var html = '<div class="sd-head"><h3>' + STAR_SVG + "Starred messages</h3><span class=\"sp\"></span>" +
      (ids.length ? '<button class="sd-btn" type="button" data-act="copy">Copy list</button>' : "") +
      '<button class="sd-btn" type="button" data-act="close" aria-label="Close">✕</button></div><div class="sd-body">';
    if (!ids.length) {
      html += '<div class="sd-empty">No starred message yet. Click the ☆ at the right of any message, in this pass or in an earlier fold.</div>';
    } else {
      var present = messages.filter(function (m) { return stars[m.id]; });
      var gone = ids.filter(function (id) { return !document.getElementById(id); });
      var groups = [];
      present.forEach(function (m) {
        var g = groups[groups.length - 1];
        if (!g || g.key !== m.num + m.subject) { g = { key: m.num + m.subject, num: m.num, subject: m.subject, rows: [] }; groups.push(g); }
        g.rows.push({ id: m.id, kind: m.kind, labelHtml: m.labelHtml, pass: m.pass, excerpt: m.excerpt });
      });
      if (gone.length) {
        groups.push({ num: "", subject: "Not in this pass", rows: gone.map(function (id) {
          var s = stars[id];
          return { id: id, kind: s.k, labelHtml: s.h || "", pass: s.p || "", excerpt: s.x || id, gone: true };
        }) });
      }
      groups.forEach(function (g) {
        html += '<div class="sd-group"><h4>' + (g.num ? '<span class="tn">' + esc(g.num) + "</span>" : "") + esc(g.subject) + "</h4>";
        g.rows.forEach(function (r) {
          var by = r.kind === "user" ? '<span class="u">Me</span>' : (r.labelHtml || '<span class="u">AI</span>');
          html += '<div class="sd-row' + (r.gone ? " gone" : "") + '"><button type="button" class="star" aria-pressed="true" data-id="' + esc(r.id) +
            '" title="Unstar" aria-label="Unstar">' + STAR_SVG + '</button><button type="button" class="go" data-go="' + esc(r.id) + '">' +
            '<div class="by">' + by + (r.pass !== "" ? '<span class="pass">· ' + esc(passLabel(r.pass)) + "</span>" : "") + "</div>" +
            '<div class="ex">' + esc(r.excerpt) + "</div></button></div>";
        });
        html += "</div>";
      });
    }
    var st = storageState();
    html += st.ok
      ? '</div><div class="sd-foot">Stars are kept in this browser for <b>' + esc(project) + "</b> (origin " + esc(st.origin) +
        "), so they carry over to the next passes opened the same way, where earlier messages stay folded in their thread.</div>"
      : '</div><div class="sd-foot warn">This viewer does not keep stars between pages (origin ' + esc(st.origin) +
        '). Open the passes in Chrome or Safari from the file, or use <b>Copy list</b> and paste it with your answers: the next pass is built with them.</div>';
    dlg.innerHTML = html;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }

  function copyList() {
    var stars = readStars();
    var lines = messages.filter(function (m) { return stars[m.id]; }).map(function (m) {
      return m.num + " " + m.subject + " · " + m.labelText + (m.pass !== "" ? " · " + passLabel(m.pass) : "") + " · #" + m.id + "\n    " + m.excerpt;
    });
    var text = "Starred messages (" + project + ")\n" + lines.join("\n");
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    var ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    ta.remove();
  }

  function countFolds() {
    document.querySelectorAll("details.earlier > summary").forEach(function (s) {
      if (s.querySelector(".cnt")) return;
      var n = s.parentElement.querySelectorAll(":scope > .msg").length;
      var span = document.createElement("span");
      span.className = "cnt";
      span.textContent = " · " + n + (n === 1 ? " message" : " messages");
      s.appendChild(span);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    setTheme(root.dataset.theme || "light");
    detectScreen();
    watchPixelRatio();
    window.addEventListener("resize", detectScreen, { passive: true });

    var themeButton = document.getElementById("theme-toggle");
    if (themeButton) themeButton.addEventListener("click", function () {
      setTheme(root.dataset.theme === "dark" ? "light" : "dark");
    });
    var tocButton = document.getElementById("toc-toggle");
    if (tocButton) tocButton.addEventListener("click", function () { setToc(!root.classList.contains("toc-open"), true); });
    setToc(root.classList.contains("toc-open"), false);
    document.addEventListener("click", function (e) {
      // Narrow windows: the pane floats over the page, so a click outside closes it.
      if (!narrow() || !root.classList.contains("toc-open")) return;
      var side = document.querySelector("aside.side");
      if (side && !side.contains(e.target) && e.target !== tocButton && !(tocButton && tocButton.contains(e.target))) setToc(false, false);
    });
    document.addEventListener("keydown", function (e) {
      if (/input|textarea|select/i.test((e.target && e.target.tagName) || "") || e.metaKey || e.ctrlKey || e.altKey) return;
      // "\" opens or closes the contents; "b" goes back to the link last clicked.
      if (e.key === "\\") setToc(!root.classList.contains("toc-open"), true);
      if (e.key === "b" && origins.length && !(document.getElementById("stars-dialog") || {}).open) goBack();
    });
    // The theme picked in another pass or in the dashboard around this page (same origin) applies here too.
    window.addEventListener("storage", function (e) {
      if (e.key === "qa-theme" && (e.newValue === "dark" || e.newValue === "light") && e.newValue !== root.dataset.theme) setTheme(e.newValue);
    });

    spy(buildToc());
    countFolds();
    indexMessages();
    applySeed();
    paintStars();

    var dlg = buildDialog();
    var starsButton = document.getElementById("stars-open");
    if (starsButton) starsButton.addEventListener("click", function () {
      renderDialog(dlg);
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    });
    document.addEventListener("click", function (e) {
      var star = e.target.closest && e.target.closest(".star[data-id]");
      if (star) {
        e.preventDefault();
        toggleStar(star.getAttribute("data-id"));
        if (dlg.open && dlg.contains(star)) renderDialog(dlg);
        return;
      }
      var go = e.target.closest && e.target.closest("[data-go]");
      if (go && dlg.contains(go)) {
        var id = go.getAttribute("data-go");
        if (document.getElementById(id)) { dlg.close(); recordOrigin(null); goTo(id, true); }
        return;
      }
      var act = e.target.closest && e.target.closest("[data-act]");
      if (act && dlg.contains(act)) {
        if (act.getAttribute("data-act") === "close") dlg.close();
        if (act.getAttribute("data-act") === "copy") {
          var done = function () { act.textContent = "Copied"; setTimeout(function () { act.textContent = "Copy list"; }, 1400); };
          var p = copyList();
          if (p && p.then) p.then(done, done); else done();
        }
      }
    });

    // In-page links in the text ("subject 05", "need item 12", a decision box, a folded message): open the
    // folds that hide the target, then go there. The contents pane keeps its own plain jump.
    document.addEventListener("click", function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var a = e.target.closest && e.target.closest('a[href^="#"]');
      if (!a || a.closest("aside.side") || dlg.contains(a)) return;
      var id = decodeURIComponent(a.getAttribute("href").slice(1));
      if (!id || !document.getElementById(id)) return;
      e.preventDefault();
      recordOrigin(a);
      goTo(id, true);
    });

    // Deep links (#p3-1a, or any id inside a closed fold) unfold what hides the target. On Back and Forward,
    // an unfolded target is left to the browser, which puts the reader back where they clicked.
    var openHash = function (onLoad) {
      if (onLoad !== true && Date.now() < restoringUntil) return;
      var id = decodeURIComponent((location.hash || "").slice(1));
      var el = id && document.getElementById(id);
      if (el && (inClosedFold(el) || (onLoad === true && el.classList.contains("msg")))) goTo(id);
    };
    window.addEventListener("hashchange", openHash);
    openHash(true);
    // Inlined images get their height while the page loads and push a deep-linked target down: align it again.
    window.addEventListener("load", function () {
      var id = decodeURIComponent((location.hash || "").slice(1));
      var el = id && document.getElementById(id);
      if (!el) return;
      var top = el.getBoundingClientRect().top;
      if (top < 0 || top > 140) { el.scrollIntoView({ behavior: "instant", block: "start" }); window.scrollBy({ top: -60, behavior: "instant" }); }
    });
  });
})();
