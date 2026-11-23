# Lane: a group session

You are one group of a batch. The triage pass sorted the batch's topics into groups, and yours are in your
brief (`brief.md` in your folder): your goal, your topics, the rules that bind you, the files you own, and the
groups you wait for. This file is what every group session does. `<group>` below is your `<batch>/<group>` path.

1. **Round 1 comes before any code.** Read your topics in the triage pass and the code they point to. Write your
   first pass in your folder (`qap carry <group>`, then `qap build <group> --check`), the qa-pass way, with every
   topic rule of SKILL.md. End it with your plan and your decisions, each with a default. Then stop, and say in
   the chat in two or three lines what you need from the user. No code until they agree to the plan.
2. **The ledger binds you.** Its rules are in your brief; `qap ledger <group>` gives the current list. A behaviour
   a user could notice that is not in it becomes a decision box in your pass, never code. When the user settles
   one, add it: `qap decide <group> --rule "…" --why "…" --who "…" --where "<the pass link>"`.
3. **Write only in your folder** (in the content root) and in your own branch of the code. Never edit a file or
   contract another group owns (your brief lists them). Ask that group instead: `qap tell <group> <other> "…"`.
4. **Say where you are** each time it changes:
   `qap status <group> --phase planning|plan_agreed|implementing|pr_open|merged|blocked [--note "…"] [--pr <url>]`.
   Never report that you wait for the user: your session's hooks do that by themselves.
5. **The smallest change wins.** "Front only" and "no backend change" are valid plans. A new RPC or table needs a
   reason in the plan. Each option says whether it fixes the cause or hides the symptom.
6. **When the user overrules your option, write down why**, in the decision you add.
7. **Your work ships as one PR**, across all its layers, never cut by layer. Follow the code repo's own PR rules.
8. **Between rounds**, the user answers in this chat or in your pass. Answer point by point in the next round
   (`qap carry <group>`), and keep the round short: the triage pass already holds the context.
9. **A note from another group** shows up in this conversation as a message from the qap mod. Read it before you
   continue; answer with `qap tell` when it asks something.
