"""Build a demo content tree with qap itself: two projects (Work and Personal), six families, fourteen subjects,
and one subject (Payment retries) with three real passes (pass 1 written here, passes 2 and 3 started by
`qap carry`). Invented topics and data. The README's screenshots are taken from it.

Usage: python3 examples/make_demo.py <new content root> [<qap>]     (qap defaults to this repo's bin/qap)
Then:  bin/qap serve --root <new content root> --open
The git screenshots: `git init --bare /tmp/backup.git`, then `bin/qap storage git init --remote file:///tmp/backup.git
--root <new content root>` before serving.
The chart needs matplotlib, which `uv run --with matplotlib` fetches on the fly.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

if len(sys.argv) not in (2, 3):
    raise SystemExit(__doc__)
ROOT = Path(sys.argv[1]).expanduser().resolve()
QAP = sys.argv[2] if len(sys.argv) == 3 else str(Path(__file__).resolve().parents[1] / "bin" / "qap")
AI = "{{AI:claude|Claude|Opus 5.5}}"


def qap(*args: str) -> dict:
    out = subprocess.run([QAP, *args, "--root", str(ROOT), "--json", "--yes"], capture_output=True, text=True)
    data = json.loads(out.stdout or "{}")
    if not data.get("ok", out.returncode == 0):
        raise SystemExit(f"qap {' '.join(args)} failed: {out.stdout}{out.stderr}")
    return data


def head(project: str, n: int, h1: str, sub: str, meta: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="qa-project" content="{project}">
<meta name="qa-pass" content="{n}">
<title>{project} — Q&amp;A pass {n}</title>
{{{{QA_PASS_HEAD}}}}
</head>
<body>
{{{{TOPBAR}}}}
<aside class="side" aria-label="On this page">
  <div class="side-h">On this page</div>
  <ol id="toc-list"></ol>
</aside>
<main class="wrap">

<header>
  <div class="kicker">{project.replace('demo-', '').replace('-', ' ')} · conversation, not a spec</div>
  <h1>Q&amp;A pass {n} — {h1}</h1>
  <p class="sub">{sub}</p>
  <div class="meta">{meta}</div>
</header>
"""


def tail(path: str, n: int) -> str:
    return f"""
<footer>
  Stored at <code>{path}</code>. This is the conversation log for pass {n}, not the spec.
  Open it in a browser (or <code>qap serve</code>).
  <div class="env" id="env"></div>
</footer>

</main>
{{{{QA_PASS_JS}}}}
</body>
</html>
"""


def write(subject: str, n: int, text: str) -> None:
    (ROOT / subject / f"QA-PASS-{n}.src.html").write_text(text, encoding="utf-8")


def fill(subject: str, n: int, replies: dict[str, tuple[str, str]], new_head: str, new_tail_from: str,
         closing: str) -> None:
    """Fill the carry placeholders of pass n (user reply + answer per subject) and rewrite head and closing."""
    path = ROOT / subject / f"QA-PASS-{n}.src.html"
    text = path.read_text(encoding="utf-8")
    for sid, (user, answer) in replies.items():
        text = re.sub(rf'(<div class="msg user" id="{sid}-{n}u"[^>]*><div class="who">Me</div>\n).*?\n</div>',
                      lambda m: m.group(1) + user + "\n</div>", text, count=1, flags=re.S)
        text = re.sub(rf'(<div class="msg ai" id="{sid}-{n}a"[^>]*><div class="who">\{{\{{AI:[^}}]+\}}\}}</div>\n).*?\n</div>',
                      lambda m: m.group(1) + answer + "\n</div>", text, count=1, flags=re.S)
    start = text.index('<h2 id="p1">')
    text = new_head + text[start:]
    text = text[:text.index(new_tail_from)] + closing
    path.write_text(text, encoding="utf-8")


def chart(img: Path) -> None:
    script = img / "recovery-by-retry.py"
    script.write_text('''"""Recovered payments per retry attempt (invented demo data)."""
import sys
sys.path.insert(0, sys.argv[1])
from chart_style import plt, style, save, VERDICT, NEUTRAL

style()
attempts = ["retry 1\\n(day 1)", "retry 2\\n(day 3)", "retry 3\\n(day 5)", "retry 4\\n(day 9)"]
recovered = [38.0, 14.2, 6.1, 1.4]
colors = [VERDICT["good"], VERDICT["good"], VERDICT["good"], VERDICT["bad"]]
fig, ax = plt.subplots(figsize=(8.5, 4.2))
bars = ax.bar(attempts, recovered, color=colors, width=0.62)
for b, v in zip(bars, recovered):
    if v > 3:
        ax.annotate(f"{v:.1f} %", (b.get_x() + b.get_width() / 2, v), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=10, fontweight="bold")
    else:  # under the gate line: the value goes right of the bar, so the line stays readable
        ax.annotate(f"{v:.1f} %", (b.get_x() + b.get_width(), v), xytext=(6, 0), textcoords="offset points",
                    ha="left", va="center", fontsize=10, fontweight="bold", color=VERDICT["bad"])
ax.set_xlim(-0.5, 4.3)
ax.axhline(3, color=NEUTRAL[1], linestyle="--", linewidth=1.2)
ax.text(4.25, 3.4, "worth a retry: 3 %", ha="right", va="bottom", fontsize=9, color=NEUTRAL[1])
ax.set_ylabel("failed payments recovered (%)")
ax.set_ylim(0, 44)
save(fig, sys.argv[2], title="Most failed payments come back on the first retry; the fourth recovers almost none", ax=ax)
''', encoding="utf-8")
    subprocess.run(["uv", "run", "--quiet", "--no-project", "--with", "matplotlib", "python", str(script),
                    str(Path(QAP).resolve().parents[1] / "skill" / "scripts"), str(img / "recovery-by-retry.png")],
                   check=True)


def small_pass(subject: str, project: str, n: int, h1: str, title: str, chip: str, question: str, answer: str,
               earlier: str = "") -> None:
    text = head(project, n, h1, "A short demo pass: one subject, one question, one answer.",
                f"pass {n} · demo content")
    text += f"""
<p class="lede">{answer}</p>

<h2 id="p1"><span class="n">01</span>{title}</h2>
<span class="chip ok">{chip}</span>
{earlier}<div class="msg user" id="p1-{n}u" data-pass="{n}"><div class="who">Me</div>
  <p>“{question}”</p>
</div>
<div class="msg ai" id="p1-{n}a" data-pass="{n}"><div class="who">{AI}</div>
  <p>{answer}</p>
</div>

<h2 id="need"><span class="n">02</span>What I need from you</h2>
<ol>
  <li>Nothing this round: reply <code>ok</code>.</li>
</ol>
""" + tail(f"{subject}/QA-PASS-{n}.html", n)
    write(subject, n, text)


def main() -> None:
    if ROOT.exists() and any(ROOT.iterdir()):
        raise SystemExit(f"{ROOT} is not empty: give a new folder")
    ROOT.mkdir(parents=True, exist_ok=True)
    for path, title, icon, color in (("payments", "Payments", "money", "#0F8B8D"),
                                     ("search", "Search", "compass", "#3478F6"),
                                     ("platform", "Platform", "layers", "#7C5CD6"),
                                     ("security", "Security", "shield", "#C2410C")):
        qap("mkdir", path, "--title", title, "--icon", icon)
        qap("icon", path, icon, "--color", color)
    subjects = (
        ("payments/payment-retries", "Payment retries", "chart", "demo-payment-retries"),
        ("payments/refunds", "Refund flow", "box", "demo-refunds"),
        ("payments/invoices", "Invoice numbering", "doc", "demo-invoices"),
        ("search/ranking", "Search ranking", "spark", "demo-search-ranking"),
        ("search/typo-tolerance", "Typo tolerance", "bulb", "demo-typo-tolerance"),
        ("platform/feature-flags", "Feature flags", "flag", "demo-feature-flags"),
        ("platform/on-call", "On-call rotation", "bell", "demo-on-call"),
        ("security/key-rotation", "API key rotation", "key", "demo-key-rotation"),
        ("onboarding-emails", "Onboarding emails", "mail", "demo-onboarding-emails"),
        ("mobile-release", "Mobile release 2.4", "rocket", "demo-mobile-release"),
    )
    for path, title, icon, project in subjects:
        qap("new-subject", path, "--title", title, "--icon", icon, "--qa-project", project)
    qap("icon", "onboarding-emails", "mail", "--color", "#E8673C")
    qap("icon", "mobile-release", "rocket", "--color", "#D6304F")

    # ---- projects: the first one holds every family made so far; Personal gets its own families ----
    qap("project", "new", "work", "--title", "Work", "--icon", "briefcase", "--color", "#2F6FDB")
    qap("project", "new", "personal", "--title", "Personal", "--icon", "home", "--color", "#1E9E3A")
    for path, title, icon, color in (("home", "Home", "🏡", "#A8650C"), ("side-projects", "Side projects", "code", "#7B2CBF")):
        qap("mkdir", path, "--title", title, "--icon", icon, "--project", "personal")
        qap("icon", path, icon, "--color", color)
    personal = (
        ("home/kitchen-renovation", "Kitchen renovation", "🛠️", "demo-kitchen"),
        ("side-projects/photo-backup", "Photo backup", "📷", "demo-photo-backup"),
        ("side-projects/reading-list", "Reading list", "book", "demo-reading-list"),
        ("half-marathon", "Half-marathon plan", "🏃", "demo-half-marathon"),
    )
    for path, title, icon, project in personal:
        qap("new-subject", path, "--title", title, "--icon", icon, "--qa-project", project, "--project", "personal")
    subjects += personal

    # ---- the showcase: payment retries, three passes ----
    s, p = "payments/payment-retries", "demo-payment-retries"
    chart(ROOT / s / "img")
    text = head(p, 1, "how often to retry a failed card payment, and when to stop",
                "You asked three questions in the chat. This file quotes you, answers you, and records what I think "
                "we now agree on. Star any message (☆ at its right) and find it again with View ★s.",
                "12 Mar 2026 · pass 1 · demo content, invented numbers")
    text += f"""
<p class="lede"><strong>Retries win back 59 % of failed card payments, and 90 % of those come back on the first
two retries.</strong> The fourth retry recovers 1.4 % and causes most of the complaints: I suggest we stop at three
(subject 02) and email the customer before the second retry, not after the last (subject 03).</p>

<div class="mantras">
  <div><b>Where we are.</b> Retry schedule measured on 90 days of failures; two decisions open (need items 1 and 2).</div>
</div>

<h2 id="p1"><span class="n">01</span>Most failed payments come back on the first retry, a day later</h2>
<span class="chip exp">recovery per retry, measured</span>
<details class="earlier"><summary>Earlier in this thread</summary>
<div class="msg ai" id="p1-0a" data-pass="0"><div class="who">{AI}</div>
  <p>I can measure the recovery per retry attempt on the last 90 days of failed payments. Shall I?</p>
</div>
</details>
<div class="msg user" id="p1-1u" data-pass="1"><div class="who">Me</div>
  <p>“yes please. how many do we actually get back, and on which retry?”</p>
</div>
<div class="msg ai" id="p1-1a" data-pass="1"><div class="who">{AI}</div>
  <p><strong>59.7 % of failed payments are recovered; the first retry alone brings back 38 %.</strong> Each later
  retry recovers less than half the one before.</p>
  <figure><img src="{{{{IMG:recovery-by-retry.png}}}}" alt="Bars per retry attempt: 38.0 %, 14.2 %, 6.1 % and 1.4 % of failed payments recovered; a dashed line at 3 % marks what is worth a retry">
    <figcaption>Read: retries 1 to 3 clear the 3 % bar; retry 4 does not. Invented demo data, 90 days, n = 4,812 failed payments.</figcaption></figure>
</div>

<h2 id="p2"><span class="n">02</span>Stop after the third retry: the fourth recovers almost nothing and angers customers</h2>
<span class="chip ask">how many retries: 3 or 4?</span>
<div class="msg user" id="p2-1u" data-pass="1"><div class="who">Me</div>
  <p>“do we need the 4th retry at all?”</p>
</div>
<div class="msg ai" id="p2-1a" data-pass="1"><div class="who">{AI}</div>
  <p><strong>No: it recovers 1.4 % and draws 61 % of the "why was I charged again" tickets.</strong></p>
  <div class="call violet" id="dec-a"><h4>Decision A: how many retries</h4>
  <ul class="opts">
    <li>✅ <strong>A1</strong> stop after 3 retries (day 5): about 67 payments a quarter not recovered, 61 % fewer complaints.</li>
    <li><strong>A2</strong> keep 4 retries (day 9): as today.</li>
  </ul>
  <p><strong>Default: A1.</strong></p></div>
</div>

<h2 id="p3"><span class="n">03</span>Email the customer before the second retry, not after the last one</h2>
<span class="chip ask">email timing: before retry 2 or after retry 3?</span>
<div class="msg user" id="p3-1u" data-pass="1"><div class="who">Me</div>
  <p>“when should the customer hear about it?”</p>
</div>
<div class="msg ai" id="p3-1a" data-pass="1"><div class="who">{AI}</div>
  <p><strong>Before the second retry.</strong> A customer who updates the card before retry 2 is recovered on
  retry 2; today the email goes after retry 4, when 98 % of what can come back already has.</p>
  <div class="call violet" id="dec-b"><h4>Decision B: when to email</h4>
  <ul class="opts">
    <li>✅ <strong>B1</strong> before retry 2 (day 2).</li>
    <li><strong>B2</strong> after the last retry, as today.</li>
  </ul>
  <p><strong>Default: B1.</strong></p></div>
</div>

<h2 id="need"><span class="n">04</span>What I need from you</h2>
<ol>
  <li><strong>A</strong> (<a href="#dec-a">decision A, how many retries</a>): <strong>A1</strong> stop at 3 · A2 keep 4. Default A1.</li>
  <li><strong>B</strong> (<a href="#dec-b">decision B, when to email</a>): <strong>B1</strong> before retry 2 · B2 after the last. Default B1.</li>
</ol>
<p>Answer line: <code>ok</code> takes every default (<code>A1 · B1</code>).</p>
<div class="call violet"><h4>What I will not do until you answer</h4>
  <p>No change to the retry schedule, no new email template.</p></div>
""" + tail(f"{s}/QA-PASS-1.html", 1)
    write(s, 1, text)
    qap("build", s, "--pass", "1")

    qap("carry", s)
    closing2 = """
<h2 id="need"><span class="n">04</span>What I need from you</h2>
<ol>
  <li><strong>C</strong> (<a href="#dec-c">decision C, expired cards</a>): <strong>C1</strong> no retry, email at once · C2 retry like other failures. Default C1.</li>
</ol>
<p>Answer line: <code>ok</code> takes the default (<code>C1</code>).</p>
<div class="call violet"><h4>What I will not do until you answer</h4>
  <p>The schedule change (A1) and the email (B1) are ready on a branch; nothing ships before C.</p></div>
""" + tail(f"{s}/QA-PASS-2.html", 2)
    fill(s, 2, {
        "p1": ("  <p>“great chart. is it the same for every card type?”</p>",
               """  <p><strong>Almost: debit cards recover a little faster, prepaid cards hardly at all.</strong></p>
  <div class="tw"><table>
    <tr><th>card</th><th class="num">failed</th><th class="num">recovered</th><th class="num">on retry 1</th></tr>
    <tr><td>credit</td><td class="num">2,904</td><td class="num">61 %</td><td class="num">39 %</td></tr>
    <tr><td>debit</td><td class="num">1,611</td><td class="num">63 %</td><td class="num">42 %</td></tr>
    <tr><td>prepaid</td><td class="num">297</td><td class="num">18 %</td><td class="num">9 %</td></tr>
  </table></div>"""),
        "p2": ("  <p>“A1. but what about expired cards, do they ever come back?”</p>",
               """  <p><strong>A1 is on the branch. Expired cards never come back by retrying: 0 of 512.</strong> They
  come back only when the customer enters a new card, so retrying them only adds charges that fail.</p>
  <div class="call violet" id="dec-c"><h4>Decision C: expired cards</h4>
  <ul class="opts">
    <li>✅ <strong>C1</strong> no retry: email at once, with a link to update the card.</li>
    <li><strong>C2</strong> retry them like any other failure.</li>
  </ul>
  <p><strong>Default: C1.</strong></p></div>"""),
        "p3": ("  <p>“B1, before is better”</p>",
               "  <p><strong>Done: the email goes out on day 2, before retry 2.</strong> Its copy is in the branch.</p>"),
    }, head(p, 2, "the schedule stops at three retries; expired cards need their own rule",
            "You answered A1 and B1, and asked about card types and expired cards. Earlier messages are folded.",
            "14 Mar 2026 · pass 2 · demo content, invented numbers") + """
<p class="lede"><strong>Stopping at three retries and emailing on day 2 is built.</strong> One new question:
expired cards never recover by retrying (0 of 512), so they should skip retries (need item 1).</p>
""", '<h2 id="need">', closing2)
    qap("build", s, "--pass", "2")

    qap("carry", s, "--skip", "p1")
    closing3 = """
<h2 id="need"><span class="n">04</span>What I need from you</h2>
<ol>
  <li>Nothing open: reply <code>ok</code> and I merge the branch.</li>
</ol>
<div class="call violet"><h4>What I will not do until you answer</h4>
  <p>No merge before your <code>ok</code>.</p></div>
""" + tail(f"{s}/QA-PASS-3.html", 3)
    fill(s, 3, {
        "p2": ("  <p>“C1 obviously”</p>",
               "  <p><strong>C1 is built: an expired card skips the retries and gets the email at once.</strong></p>"),
        "p3": ("  <p>“can the email say how much is due?”</p>",
               "  <p><strong>Yes: the amount and the due date are in the subject line now.</strong></p>"),
    }, head(p, 3, "everything you chose is built and ready to merge",
            "You chose C1 and asked for the amount in the email. Earlier messages are folded.",
            "16 Mar 2026 · pass 3 · demo content, invented numbers") + """
<p class="lede"><strong>A1, B1 and C1 are built on one branch.</strong> Recovery stays at 58 % (one point lower)
with 61 % fewer complaints.</p>
""", '<h2 id="need">', closing3)
    qap("build", s, "--pass", "3")

    # ---- the other tiles: one or two short passes each ----
    smalls = {
        "payments/refunds": ("Refunds go back to the original card within 5 days", "refund path decided",
                             "can refunds go to a different card?",
                             "No: card networks send a refund to the card that paid. A different card is a new payout."),
        "payments/invoices": ("Invoice numbers stay sequential per country", "numbering decided",
                              "do invoice numbers need to be sequential?",
                              "Yes, per country and without gaps; a cancelled invoice keeps its number."),
        "search/ranking": ("Fresh items get a 7-day boost, then rank on clicks alone", "ranking rule agreed",
                           "should new items rank higher?",
                           "For 7 days only: after that, clicks rank them better than any boost."),
        "search/typo-tolerance": ("One typo is forgiven in words of 5 letters or more", "rule agreed",
                                  "how many typos do we tolerate?",
                                  "One per word, from 5 letters; shorter words must match exactly."),
        "platform/feature-flags": ("A flag older than 90 days opens a clean-up ticket", "policy agreed",
                                   "how do we stop flags piling up?",
                                   "Every flag gets an owner and an expiry; at 90 days the owner gets a ticket."),
        "platform/on-call": ("On-call weeks start on Tuesday, after the release", "rotation agreed",
                             "monday handovers keep failing, why?",
                             "They land on release day. Starting on Tuesday moves the handover away from it."),
        "security/key-rotation": ("API keys rotate every 90 days, with a 7-day overlap", "rotation agreed",
                                  "how do we rotate keys without downtime?",
                                  "The old and the new key both work for 7 days; clients switch in that window."),
        "onboarding-emails": ("Three emails, not five: day 0, day 2 and day 7", "sequence agreed",
                              "are five onboarding emails too many?",
                              "Yes: emails 4 and 5 are opened by 6 % and drive no sign-in. Keep three."),
        "mobile-release": ("Release 2.4 ships to 10 % first, then everyone after 48 hours", "rollout agreed",
                           "how do we roll out 2.4?",
                           "Staged: 10 % for 48 hours, then 100 % if crash-free sessions stay above 99.5 %."),
        "home/kitchen-renovation": ("Order the worktop first: it takes six weeks", "plan agreed",
                                    "what do we order first?",
                                    "The worktop: six weeks to cut. The cabinets take two, the tiles one."),
        "side-projects/photo-backup": ("Back up the photos twice: a disk at home and one copy off-site", "setup agreed",
                                       "is one external disk enough?",
                                       "No: one disk is one failure away from losing everything. Keep a second copy off-site."),
        "side-projects/reading-list": ("Three books a month, picked on the first Sunday", "habit agreed",
                                       "how do I stop the list from growing forever?",
                                       "Pick three on the first Sunday of the month; the rest waits, unread, guilt-free."),
        "half-marathon": ("Twelve weeks, four runs a week, one long run on Sunday", "plan agreed",
                          "how long do I need to train for a half-marathon?",
                          "Twelve weeks from 25 km a week: four runs, the long one on Sunday, +10 % a week at most."),
    }
    projects = {path: project for path, _, _, project in subjects}
    for path, (title, chip, question, answer) in smalls.items():
        small_pass(path, projects[path], 1, title.lower(), title, chip, question, answer)
        qap("build", path, "--pass", "1")
    for path in ("search/ranking", "mobile-release"):
        small_pass(path, projects[path], 2, smalls[path][0].lower(), smalls[path][0], smalls[path][1],
                   "ok, go", "Done; the next pass will carry the numbers from the first week.")
        qap("build", path, "--pass", "2")


if __name__ == "__main__":
    main()
