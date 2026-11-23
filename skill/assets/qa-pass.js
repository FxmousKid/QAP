// QA pass page behaviour: theme toggle, the contents pane (fixed, never pushes the article) with scroll-spy and
// what moved since the last pass (NEW signs, counts, "Only what's new"),
// screen detection (pixel ratio, width tier, ultrawide), message labels (pass + star on every message) and
// the "View ★s" dialog, a reference list of starred messages, the "back to where I clicked" button, and the
// search over every pass when the page is served by `qap serve`; in a triage pass, each group's latest round
// shown inside the page (served), and a page opened with ?embed=1 drawn as that frame.
// The theme, the pane state and the pixel ratio are first applied before paint by the inline boot snippet in
// <head> (THEME_BOOT in build.py); this file keeps them up to date.
(function () {
  var root = document.documentElement;
  // ?embed=1: this page is a group's round shown inside its triage pass. No top bar, no contents pane, no
  // footer; it tells the page around it its height, so the frame grows instead of scrolling.
  var EMBEDDED = /(?:^|&)embed=1(?:&|$)/.test(location.search.slice(1)) && window.parent !== window;
  if (EMBEDDED) root.classList.add("embedded");
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
    placeTop();  // the toggle's width changes with its label
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
    placeTop();  // the top row's buttons moved (window width, star count): the back button's room follows
  }

  // The right-hand buttons sit side by side from the right edge: View ★s, the theme toggle, Share, then Search.
  // Each one's offset is the widths of those right of it, which change with the star count and the theme label.
  function placeTop() {
    var stars = document.getElementById("stars-open");
    var theme = document.getElementById("theme-toggle");
    var share = document.getElementById("share-open");
    if (stars) root.style.setProperty("--stars-w", stars.offsetWidth + "px");
    if (theme) root.style.setProperty("--theme-w", theme.offsetWidth + "px");
    if (share) root.style.setProperty("--share-w", share.offsetWidth + "px");
    placeBack();
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

  // The number of a heading, without the NEW sign markNews draws inside it.
  function numText(n) {
    return n ? Array.prototype.filter.call(n.childNodes, function (c) {
      return !(c.nodeType === 1 && c.classList.contains("sign"));
    }).map(function (c) { return c.textContent; }).join("").trim() : "";
  }

  // A heading picked in the pane flashes once the (smooth) jump has landed on it, so the reader sees which one.
  // Landed: the heading has not moved for 8 frames (scrollend does not fire for an anchor jump everywhere).
  function flashWhenLanded(el) {
    var last = null, still = 0, start = Date.now();
    (function check() {
      var top = Math.round(el.getBoundingClientRect().top);
      still = top === last ? still + 1 : 0;
      last = top;
      if (still < 8 && Date.now() - start < 4000) { requestAnimationFrame(check); return; }
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    })();
  }

  function buildToc() {
    var list = document.getElementById("toc-list");
    if (!list) return [];
    var links = [];
    var group = null;  // the list of the group heading above, while topics follow it
    document.querySelectorAll("main h2[id]").forEach(function (h2) {
      var a = document.createElement("a");
      a.href = "#" + h2.id;
      var num = h2.querySelector(".n");
      if (num) {
        var tn = document.createElement("span");
        tn.className = "tn";
        tn.textContent = numText(num);
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
      a.addEventListener("click", function () {
        if (narrow()) setToc(false, false);
        flashWhenLanded(h2);
      });
      var li = document.createElement("li");
      li.appendChild(a);
      // A group heading (h2.grp) holds the topics after it, indented under it, until the next group or a
      // closing section (What I need from you).
      if (h2.classList.contains("grp")) {
        li.className = "grp";
        li.setAttribute("data-group", h2.getAttribute("data-group") || "");
        group = document.createElement("ol");
        li.appendChild(group);
        list.appendChild(li);
      } else if (group && /^p\d+$/.test(h2.id)) {
        group.appendChild(li);
      } else {
        group = null;
        list.appendChild(li);
      }
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

  // ---- what moved since the last pass ----
  // build.py stamps each subject h2: data-new="subject|round" (it moved in this pass), data-since="P" (its latest
  // pass), data-asks="S R" (the decisions it asks); h2#need gets data-items. Drawn here: a NEW sign on the
  // pane's line left of the number (filled: a new subject; outlined: a new round) and after the number in the
  // heading, a violet pill for what waits for you, and the counts with "Only what's new" above the list.
  var SPARK = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 .8l1.3 3.9 3.9 1.3-3.9 1.3L6 11.2 4.7 7.3.8 6l3.9-1.3z" fill="currentColor"/></svg>';

  function newSign(h2, inHeading) {
    var kind = h2.getAttribute("data-new");
    var sign = document.createElement("span");
    sign.className = "sign " + kind;
    sign.title = (kind === "subject" ? "New subject in pass " : "New round in pass ") + h2.getAttribute("data-since");
    sign.innerHTML = (inHeading ? SPARK : "") + "NEW";
    return sign;
  }

  function markNews(links) {
    var list = document.getElementById("toc-list");
    if (!list || !document.querySelector("main h2[data-new]")) return;
    var moved = 0, same = 0, waits = 0;
    links.forEach(function (l) {
      var h2 = l.target, li = l.a.parentNode;
      if (h2.hasAttribute("data-new")) {
        moved++;
        li.classList.add("moved");
        li.insertBefore(newSign(h2, false), l.a);
        var n = h2.querySelector(".n");
        if (n && !n.querySelector(".sign")) n.appendChild(newSign(h2, true));
      } else if (h2.hasAttribute("data-since")) {
        same++;
        li.classList.add("same");
        l.a.title = "Unchanged since pass " + h2.getAttribute("data-since");
      }
      var asks = h2.getAttribute("data-asks") || h2.getAttribute("data-items");
      if (!asks || asks === "0") return;
      var pill = document.createElement("span");
      pill.className = "asks";
      pill.textContent = asks;
      pill.title = h2.id === "need" ? asks + " waiting for your answer" : "Waits for your answer: " + asks;
      l.a.insertBefore(pill, l.a.firstChild);
      if (h2.id === "need") waits = parseInt(asks, 10) || 0;
    });
    var box = document.createElement("div");
    box.className = "news";
    var counts = document.createElement("div");
    counts.className = "news-n";
    counts.innerHTML = '<span><b class="g">' + moved + "</b> new</span>" +
      (waits ? ' · <span><b class="v">' + waits + "</b> " + (waits === 1 ? "waits" : "wait") + " for you</span>" : "") +
      (same ? " · <span>" + same + " unchanged</span>" : "");
    var label = document.createElement("label");
    var only = document.createElement("input");
    only.type = "checkbox";
    only.checked = load("qa-only-new") === "1";
    label.appendChild(only);
    label.appendChild(document.createTextNode("Only what's new"));
    var apply = function () { list.classList.toggle("only-new", only.checked); };
    only.addEventListener("change", function () { apply(); store("qa-only-new", only.checked ? "1" : "0"); });
    apply();
    box.appendChild(counts);
    box.appendChild(label);
    list.parentNode.insertBefore(box, list);
    list.classList.add("has-news");
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
        subject = { num: numText(n), title: h2Title(el), id: el.id };
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
    var first = document.getElementById("search-open") || document.getElementById("share-open") || document.getElementById("theme-toggle");  // the right group's leftmost
    var b = document.getElementById("back-to-link");
    var left = toc ? toc.getBoundingClientRect().right + 8 : 16;
    var room = Math.floor((first ? first.getBoundingClientRect().left - 8 : window.innerWidth - 16) - left);
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

  // ---- search over every project, family, subject and pass ----
  // Only a server has the index (GET /api/search), so this needs the page served by `qap serve`.
  //  - Inside the dashboard's frame (same origin), the dashboard owns the search: its bar has the button (left of ‹)
  //    and its listener on this page turns ⌘K into its dialog; / opens its pass list.
  //  - Opened alone from qap serve, the page gets a Search button in the top row, left of the theme toggle. It loads
  //    the dashboard's own search module (/ui/search.js) on first use; a result opens in the dashboard. ⌘K or /.
  //  - Opened as a file (or from another server), there is no button; ⌘K or / says how to get search.
  var SEARCH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20.5 20.5"/></svg>';
  var searchModule = null;

  function dashboard() {
    try { return window.parent !== window && window.parent.qapDashboard ? window.parent.qapDashboard : null; }
    catch (e) { return null; }  // a frame from another origin
  }

  function openSearch() {
    var dash = dashboard();
    if (dash) { dash.openSearch(); return; }
    if (!document.getElementById("search-open")) { searchHint(); return; }
    if (!searchModule) searchModule = import("/ui/search.js");
    searchModule.then(function (m) { m.configure({ prefix: "/" }); return m.openSearch(); },
      function () { searchModule = null; searchHint(); });
  }

  function searchHint() {
    var note = document.getElementById("search-hint");
    if (!note) {
      note = document.createElement("div");
      note.id = "search-hint";
      note.setAttribute("role", "status");
      document.body.appendChild(note);
    }
    note.textContent = "Search needs the dashboard: open this pass through qap serve --open.";
    note.hidden = false;
    clearTimeout(note.qapTimer);
    note.qapTimer = setTimeout(function () { note.hidden = true; }, 5000);
  }

  function setupSearch() {
    document.addEventListener("keydown", function (e) {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey) {
        if (dashboard()) return;  // the dashboard's listener on this page opens its own dialog
        e.preventDefault();
        openSearch();
        return;
      }
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || dashboard()) return;
      var t = e.target;
      if (/input|textarea|select/i.test((t && t.tagName) || "") || (t && t.isContentEditable)) return;
      if ((document.getElementById("stars-dialog") || {}).open) return;
      e.preventDefault();
      openSearch();
    });
    if (dashboard() || !/^https?:$/.test(location.protocol) || !window.fetch) return;
    // Served over http: show the button only when that server is qap's (it has the search module).
    fetch("/ui/search.js", { method: "HEAD", cache: "no-store" }).then(function (res) {
      if (!res.ok || document.getElementById("search-open")) return;
      var b = document.createElement("button");
      b.type = "button";
      b.className = "topbtn";
      b.id = "search-open";
      b.title = "Search every project, family, subject and pass (" + (/Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘K" : "Ctrl+K") + " or /)";
      b.setAttribute("aria-label", "Search");
      b.innerHTML = SEARCH_SVG + '<span class="lbl">Search</span>';
      b.addEventListener("click", openSearch);
      var theme = document.getElementById("theme-toggle");
      document.body.insertBefore(b, theme || document.body.firstChild);
      placeTop();
    }, function () {});
  }

  // ---- embedded: report the height to the triage pass around this page ----
  function setupEmbedded() {
    if (!EMBEDDED) return;
    var last = 0;
    var report = function () {
      var h = Math.ceil(document.documentElement.scrollHeight);
      if (h === last) return;
      last = h;
      try { window.parent.postMessage({ qap: "height", height: h }, location.origin); } catch (e) {}
    };
    if (window.ResizeObserver) new ResizeObserver(report).observe(document.body);
    window.addEventListener("load", report);
    document.addEventListener("toggle", report, true);
    report();
    // A link to another page opens it in the whole window, not inside the frame.
    document.querySelectorAll("a[href]").forEach(function (a) {
      if (a.getAttribute("href").charAt(0) !== "#" && !a.target) a.target = "_top";
    });
  }

  // ---- a triage pass shows each session group's latest round inside it ----
  // Served by qap serve, each group heading gets a frame at the end of its topics: the group's latest page,
  // with ?embed=1, and its state from GET /api/board (re-read every few seconds; a new round reloads the frame).
  // Opened as a file, the frame is a link to the group's folder instead (browsers isolate file:// frames).
  var LANES = {
    needs_you: ["live-you", function (g) {
      return (g.session.state === "permission" ? "Asks for a permission" : "Waits for you") + since(g.session.since);
    }],
    working: ["live-work", function () { return "Working"; }],
    waits: ["live-wait", function (g) { return "Waits for " + (g.blocked_by.join(", ") || "another group"); }],
    stopped: ["live-wait", function () { return "Session ended"; }],
    ready: ["live-wait", function () { return "Not started"; }],
    done: ["live-done", function (g) { return g.phase === "merged" ? "Merged" : "Done"; }]
  };

  function since(iso) {
    var ms = Date.now() - Date.parse(iso || "");
    if (!(ms >= 0)) return "";
    var min = Math.round(ms / 60000);
    return min < 1 ? " · just now" : min < 60 ? " · " + min + " min" : " · " + Math.round(min / 60) + " h";
  }

  function setupGroups() {
    if (meta("qa-kind") !== "triage" || EMBEDDED) return;
    var heads = Array.prototype.slice.call(document.querySelectorAll('main h2.grp[data-lane="session"][data-group]'));
    if (!heads.length) return;
    var served = /^https?:$/.test(location.protocol) && !!window.fetch && location.pathname.indexOf("/c/") === 0;
    var parts = decodeURIComponent(location.pathname.slice(3)).split("/");
    var batch = parts.slice(0, -2).join("/");  // /c/<batch>/triage/QA-PASS-N.html
    var frames = {};
    heads.forEach(function (h2) {
      var name = h2.getAttribute("data-group");
      var box = document.createElement("section");
      box.className = "gframe";
      box.setAttribute("aria-label", "Group " + name + ": its latest round");
      var head = document.createElement("div");
      head.className = "gf-head";
      var chip = document.createElement("span");
      chip.className = "chip live-wait";
      chip.textContent = served ? "…" : "Opened as a file";
      var label = document.createElement("span");
      label.className = "gf-label";
      label.textContent = served ? "Group " + name : "Open this page with qap serve to see the group's latest round here.";
      var open = document.createElement("a");
      open.className = "gf-open";
      open.textContent = "Open the group's thread";
      open.href = served ? "/#/" + batch + "/" + name : "../" + name + "/";
      // A round is long: the frame shows its first screenful until the reader asks for the whole round.
      var more = document.createElement("button");
      more.type = "button";
      more.className = "gf-more";
      more.textContent = "Show the whole round";
      more.hidden = true;
      more.addEventListener("click", function () {
        var folded = box.classList.toggle("folded");
        more.textContent = folded ? "Show the whole round" : "Fold it back";
      });
      box.classList.add("folded");
      head.appendChild(chip); head.appendChild(label); head.appendChild(more); head.appendChild(open);
      box.appendChild(head);
      var body = document.createElement("div");
      body.className = "gf-empty";
      body.textContent = served ? "No round yet: the group's session writes its first one." : "";
      if (served) box.appendChild(body);
      // The frame goes after the group's last topic: before the next group heading or closing section.
      var next = h2.nextElementSibling;
      while (next && !(next.tagName === "H2" && (next.classList.contains("grp") || !/^p\d+$/.test(next.id)))) next = next.nextElementSibling;
      h2.parentNode.insertBefore(box, next);
      frames[name] = { box: box, chip: chip, label: label, open: open, more: more, body: body, frame: null, src: "" };
    });
    if (!served) return;

    window.addEventListener("message", function (e) {
      if (e.origin !== location.origin || !e.data || e.data.qap !== "height") return;
      Object.keys(frames).forEach(function (name) {
        var f = frames[name];
        if (!f.frame || f.frame.contentWindow !== e.source) return;
        f.frame.style.height = Math.max(120, e.data.height) + "px";
        f.more.hidden = e.data.height <= f.box.clientWidth * 0.9;
      });
    });

    var board = document.createElement("a");
    board.className = "gboard";
    board.href = "/ui/board.html#" + encodeURIComponent(batch);
    board.textContent = "The live board of this batch";
    var where = document.querySelector("main header .meta") || document.querySelector("main header");
    if (where) where.parentNode.insertBefore(board, where.nextSibling);

    var refresh = function () {
      fetch("/api/board?path=" + encodeURIComponent(batch), { cache: "no-store" }).then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || !data.ok) return;
          data.groups.forEach(function (g) {
            var f = frames[g.name];
            if (!f) return;
            var lane = LANES[g.lane] || LANES.ready;
            f.chip.className = "chip " + lane[0];
            f.chip.textContent = lane[1](g);
            f.label.textContent = g.round ? "Round " + g.round + (g.note ? " · " + g.note : "") : "Group " + g.name;
            if (g.page) f.open.href = g.page;
            var tocItem = document.querySelector('aside.side li.grp[data-group="' + g.name + '"] > a');
            if (tocItem) {
              var live = tocItem.querySelector(".chip.live") || tocItem.appendChild(document.createElement("span"));
              live.className = "chip live " + lane[0];
              live.textContent = f.chip.textContent;
            }
            var src = g.page ? g.page + "?embed=1&v=" + encodeURIComponent(g.page_mtime) : "";
            if (!src || src === f.src) return;
            f.src = src;
            if (!f.frame) {
              f.frame = document.createElement("iframe");
              f.frame.title = "Group " + g.name + ", round " + g.round;
              f.box.replaceChild(f.frame, f.body);
            }
            f.frame.src = src;
          });
        }, function () {});
    };
    refresh();
    setInterval(function () { if (!document.hidden) refresh(); }, 8000);
  }

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

  // Keep this in step with qap.share.redact: a home directory becomes ~, and a URL like
  // https://example.com/home/ivan is left alone (a letter sits against the slash).
  var HOME_PATH = /(?<![A-Za-z0-9._-])(?:(?:file:\/\/(?:localhost)?)?(?:\/Users|\/home)\/[^/\s"'<>]+|%2F(?:Users|home)%2F(?:%[0-9A-Fa-f]{2}|[^%/\s"'<>])+)/gi;

  function redactText(text) {
    HOME_PATH.lastIndex = 0;
    return String(text).replace(HOME_PATH, function (raw) {
      var core = raw.replace(/[.,;:)\]}>]+$/, "");
      return "~" + raw.slice(core.length);
    });
  }

  function qapHost() {
    return /^https?:$/.test(location.protocol) && /^(127\.0\.0\.1|localhost)(:\d+)?$/.test(location.host);
  }

  function passRel() {
    var path = location.pathname;
    try { path = decodeURIComponent(path); } catch (e) { /* keep the raw path */ }
    return path.indexOf("/c/") === 0 ? path.slice(3).replace(/^\/+/, "") : "";
  }

  function downloadName(res, fallback) {
    var disp = (res && res.headers && res.headers.get("Content-Disposition")) || "";
    var star = /filename\*=UTF-8''([^;]+)/i.exec(disp);
    if (star) {
      try { return decodeURIComponent(star[1].trim()); } catch (e) { /* the plain name below */ }
    }
    var plain = /filename="([^"]*)"/.exec(disp);
    return (plain && plain[1]) || fallback || "QA-PASS.html";
  }

  function downloadBlob(blob, name) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name || "QA-PASS.html";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1500);
  }

  function downloadDocument() {
    var name = "QA-PASS.html";
    try { name = decodeURIComponent((location.pathname.split("/").pop() || name).split("?")[0]); } catch (e) {}
    downloadBlob(new Blob(["<!DOCTYPE html>\n" + redactText(document.documentElement.outerHTML)], { type: "text/html" }), name);
  }

  function downloadFromServer() {
    var rel = passRel();
    if (!rel || !qapHost()) { downloadDocument(); return; }
    fetch("/api/share/file?path=" + encodeURIComponent(rel)).then(function (res) {
      if (!res.ok) { downloadDocument(); return; }
      return res.blob().then(function (blob) { downloadBlob(blob, downloadName(res, rel.split("/").pop())); });
    }, downloadDocument);
  }

  function shareNote(text) {
    var note = document.getElementById("share-note");
    if (!note) {
      note = document.createElement("div");
      note.id = "share-note";
      note.setAttribute("role", "status");
      document.body.appendChild(note);
    }
    note.textContent = text;
    note.hidden = false;
    clearTimeout(note.qapTimer);
    note.qapTimer = setTimeout(function () { note.hidden = true; }, 12000);
  }

  function sendFromPage() {
    var rel = passRel();
    if (!rel) { shareNote("Open this pass from the dashboard to send it."); return; }
    fetch("/api/share?path=" + encodeURIComponent(rel)).then(function (res) { return res.json(); }).then(function (info) {
      if (!info.ok) throw new Error(info.error || "could not read the share command");
      openSharePreview(info, rel);
    }).catch(function (err) { shareNote(err.message || "could not read the share command"); });
  }

  function openSharePreview(info, rel) {
    var old = document.getElementById("share-dialog");
    if (old) old.remove();
    var ready = !!(info.command && String(info.command).trim());
    var dlg = document.createElement("dialog");
    dlg.id = "share-dialog";
    var form = document.createElement("form");
    var title = document.createElement("h3");
    title.textContent = ready ? "Send this pass" : "Share command";
    var hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = ready
      ? "The template is the one in the config. Each value is in double quotes. The copy's directory is chosen when you send."
      : "Set the template on this machine. The page keeps no command of its own.";
    var pre = document.createElement("pre");
    pre.className = "cmd";
    pre.textContent = ready ? (info.preview || "") : "qap config share_command '" + (info.suggested || "") + "'";
    var row = document.createElement("div");
    row.className = "row";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "sd-btn";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", function () { dlg.close(); });
    row.appendChild(cancel);
    if (ready) {
      var go = document.createElement("button");
      go.type = "submit";
      go.className = "sd-btn";
      go.textContent = "Send";
      row.appendChild(go);
    }
    form.appendChild(title);
    form.appendChild(hint);
    form.appendChild(pre);
    form.appendChild(row);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      dlg.close();
      shareNote("Sending…");
      fetch("/api/share/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: rel }),
      }).then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      }).then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.error) || "send failed");
        shareNote(r.data.url || (r.data.stdout || "Sent").trim() || "Sent");
      }).catch(function (err) { shareNote(err.message || "send failed"); });
    });
    dlg.appendChild(form);
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
    document.body.appendChild(dlg);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    (goButton(row) || cancel).focus();
  }

  function goButton(row) {
    return row.querySelector("button[type=submit]");
  }

  function closeShareMenu() {
    var menu = document.getElementById("share-menu");
    if (menu) menu.remove();
  }

  function toggleShareMenu(anchor) {
    if (document.getElementById("share-menu")) { closeShareMenu(); return; }
    var menu = document.createElement("div");
    menu.id = "share-menu";
    menu.setAttribute("role", "menu");
    [["Download HTML", downloadFromServer], ["Send", sendFromPage]].forEach(function (item) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.textContent = item[0];
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        closeShareMenu();
        item[1]();
      });
      menu.appendChild(b);
    });
    document.body.appendChild(menu);
    var r = anchor.getBoundingClientRect();
    menu.style.top = (r.bottom + 6) + "px";
    menu.style.right = Math.max(8, window.innerWidth - r.right) + "px";
  }

  function setupShare() {
    if (document.getElementById("share-open")) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "topbtn";
    b.id = "share-open";
    b.textContent = "Share";
    b.title = "Download this page, or send it with the saved command";
    b.setAttribute("aria-haspopup", "menu");
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      if (!qapHost()) { downloadDocument(); return; }
      toggleShareMenu(b);
    });
    var theme = document.getElementById("theme-toggle");
    if (theme) theme.parentNode.insertBefore(b, theme);
    else document.body.appendChild(b);
    document.addEventListener("click", function (e) {
      var menu = document.getElementById("share-menu");
      if (!menu || menu.contains(e.target) || e.target === b) return;
      closeShareMenu();
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeShareMenu(); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupShare();
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

    setupSearch();
    var tocLinks = buildToc();
    spy(tocLinks);
    setupEmbedded();
    setupGroups();
    countFolds();
    indexMessages();
    applySeed();
    paintStars();
    markNews(tocLinks);

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
