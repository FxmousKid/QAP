# Lane: the triage session of a batch

A batch is independent problems worked on side by side: one session per group, each with its own thread and its
own pass. You sort the topics, then start the other sessions.

0. **Be sure it is a batch** (SKILL.md, "Batches"). Many topics about one feature, one bug or one contract are one
   ordinary pass, even across the database, the web and the apps. A batch needs at least two groups that two
   people could work on at the same time without talking to each other. Otherwise stop here and write an
   ordinary pass.
1. **Create the batch.** `qap new-batch <family>/<batch> --title "…"` makes the folder and starts its triage pass
   from the triage template. Seed the ledger with the rules already known (from the user, a meeting, a review):
   `qap decide <batch>/triage --rule "…" --why "…" --who "…" --where "<link>"`.
2. **Write the triage pass.** Two or three lines per topic: what the user sees, where it comes from (a link), the
   decision it needs. The depth goes into the groups.
   - **The grouping test.** Two topics share a group when they need the same decision, when their fixes change
     the same contract (what a function does, a policy, what a status means, an API schema), or when one person
     would naturally fix them together in the same code. Never split one feature by layer (a database group, a
     web group): it ships as one PR across the layers. In doubt, merge: fewer groups is better.
   - **At least two session groups.** If the test leaves one, this is not a batch: write an ordinary pass.
   - **One owner per shared file.** A file or contract two groups would edit belongs to one of them. The other
     waits for its PR (`data-waits`).
   - **Not everything needs a session.** A clear fix with no product question and files of its own goes to the
     fast lane (one PR each). A topic with nothing to change goes to the info list.
   - **Order the session groups** by urgency: a production bug or a cutover risk first. A group that waits for
     another comes after it.
3. **Check it.** `qap build <batch>/triage --check` fails a topic in no group, a session group without a folder
   name, or a file two groups own. Hand the pass over; the user answers "groups ok" or moves topics.
4. **Split.** `qap split <batch>` creates one subject per session group with its brief, and lists the groups to
   start now, each with its first prompt (one line).
5. **Start exactly those.** One session per group, in its own worktree of the code repo, with exactly that first
   prompt and nothing else:
   - in the Claude app, start a fresh session per group (title: the group's title; name: its folder name; its own
     worktree). The qap mod's board pane beside this chat then shows each one, and Jump opens it in split view;
   - in a terminal, one tab per group: `claude -n <group> "<first prompt>"` (or the Codex CLI).
   Start the next ones when `qap board <batch>` lists them under "start next".
6. **While they run.** The board says who waits for the user; they answer in each group's own session, and you
   never relay their answers. Keep the batch: rerun `qap split` after a triage change, start the next wave, and
   review each group's PR when it opens, with a fresh reviewer that sees only the ledger and the diff.
