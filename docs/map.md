# Map

Each row is a rule the code has to keep, the place that implements it, and the test that fails when the rule breaks.

The whole suite, from the repository root:

```bash
uv run --project . python -m unittest discover -s tests
```

## Rules

| Rule | Code | Test |
| --- | --- | --- |
| A project is a box on the home screen. A family joins it through the project field of its manifest, and the folder stays where it is. | `src/qap/layout/project.py` | `tests.test_layout.Projects.test_assign_move_up_and_refusals` |
| qa_project in the page meta is the key stars are stored under. | `src/qap/skill.py` | `tests.test_cli_server.CLI.test_flow` |
| Project membership is separate from the folder the subject lives in. | `src/qap/layout/project.py` | `tests.test_cli_server.CLI.test_projects` |
| The first project is the default. Every family that has no project yet belongs to it. | `src/qap/layout/project.py` | `tests.test_layout.Projects.test_first_project_is_the_default_and_holds_everything` |
| Changing the default writes the previous default onto families that had none, so they stay in the project they already belonged to. | `src/qap/layout/project.py` | `tests.test_layout.Projects.test_a_new_default_never_moves_existing_folders` |
| With no projects file, the tree is the list of families. | `src/qap/layout/read.py` | `tests.test_layout.Projects.test_no_projects_reads_as_before` |
| remove_folder removes an empty folder. A folder that still holds a subject stays. | `src/qap/layout/write.py` | `tests.test_layout.Writing.test_remove_folder_only_when_empty` |
| A dashboard write is accepted when Host and Origin are this server. | `src/qap/server.py` | `tests.test_cli_server.Server.test_writes_are_guarded_and_work` |
| A plugin that raises while loading is left off, and qap keeps running. | `src/qap/plugins.py` | `tests.test_plugins.Lifecycle.test_a_broken_plugin_never_breaks_qap` |
| Unload removes the commands, routes and events that onload added. | `src/qap/plugins.py` | `tests.test_plugins.Lifecycle.test_unload_removes_everything_onload_added` |
| Enabling a community plugin is done with qap plugins enable. The dashboard answers 403. | `src/qap/plugins.py` | `tests.test_plugins.ServerRoutes.test_writes_are_guarded_and_enable_disable_live` |
| git-storage pushes without --force. | `src/qap/core_plugins/git-storage/store.py` | `tests.test_git_storage.GitStorage.test_never_force_pushes` |
| A merge conflict stops the sync. | `src/qap/core_plugins/git-storage/store.py` | `tests.test_git_storage.GitStorage.test_conflict_stops_shows_and_resolves` |
| A merge qap left unfinished is aborted. A merge started outside qap is left in place. | `src/qap/core_plugins/git-storage/store.py` | `tests.test_git_storage.GitStorage.test_a_merge_left_half_done_by_qap_is_undone_and_anyone_elses_is_left_alone` |
| A background commit is unsigned unless sign_commits is inherit. | `src/qap/core_plugins/git-storage/store.py` | `tests.test_git_storage.GitStorage.test_background_commits_are_not_signed_by_default` |
| A built page that has a source is gitignored, and it is rebuilt after a pull or a restore. | `src/qap/core_plugins/git-storage/store.py` | `tests.test_git_storage.GitStorage.test_built_pages_are_left_out_and_rebuilt_after_a_restore_or_a_pull` |
| A content root inside another git repository is refused. | `src/qap/core_plugins/git-storage/store.py` | `tests.test_git_storage.GitStorage.test_a_content_root_inside_another_repository` |
| need item N in an earlier pass's message links to that pass's page. | `skill/scripts/build.py` | `tests.test_build.NeedItemsOfEarlierPasses.test_an_earlier_ai_message_links_to_its_own_pass` |
| need item N outside a message links to this page's list. | `skill/scripts/build.py` | `tests.test_build.NeedItemsOfEarlierPasses.test_this_pass_and_text_outside_messages_keep_the_local_list` |
| A comment, a pre, a code span, and the text of a quoted attribute are copied unchanged when references are linked. | `skill/scripts/html_span.py` | `tests.test_build.NeedItemsOfEarlierPasses.test_a_comment_a_pre_and_a_quoted_gt_are_not_linked` |
| carry moves each open message into details.earlier byte for byte and writes the new round's TODO placeholders. | `skill/scripts/carry.py` | `tests.test_pages.Carry.test_open_messages_move_byte_for_byte_into_the_fold` |
| A closing tag written inside a comment or a quoted attribute does not end the message carry is moving. | `skill/scripts/html_span.py` | `tests.test_pages.Carry.test_a_comment_and_a_quoted_gt_do_not_end_a_message` |
| skip leaves that subject open. stars writes the copied message ids into the new page. | `skill/scripts/carry.py` | `tests.test_pages.Carry.test_skip_keeps_the_round_open_and_stars_are_seeded` |
| decision_codes follows the examples next to the regex. | `skill/scripts/check.py` | `tests.test_pages.Check.test_decision_codes_match_the_table` |
| check exits 1 when the page has a problem, and exits 0 when the only findings are warnings. | `skill/scripts/check.py` | `tests.test_pages.Check.test_problems_fail_and_a_sound_page_does_not` |
| seed_first fills the three PROJECT slots and escapes the project name. | `src/qap/skill.py` | `tests.test_pages.Seed.test_only_the_three_template_slots_are_filled` |
| The second search returns the cached index and does not open the pages again. | `src/qap/snapshot.py` | `tests.test_snapshot.Snapshot.test_the_second_read_does_not_open_the_pages_again` |
| Editing a pass file changes the cached tree. | `src/qap/snapshot.py` | `tests.test_snapshot.Snapshot.test_editing_a_pass_invalidates_the_cache` |
| The next GET /api/tree after a pass file changes shows the new title. | `src/qap/server.py` | `tests.test_cli_server.Server.test_a_changed_pass_shows_up_on_the_next_read` |
| Every test named in this file is a real test. | `tests/test_map.py` | `tests.test_map.Map.test_every_named_test_exists` |
| Every file named under After a change exists. | `docs/map.md` | `tests.test_map.Map.test_every_named_file_exists` |

## After a change

Run the command for the files you edited. Prefix it with `uv run --project .` so the command uses this repository's Python.

| Files | Command |
| --- | --- |
| `src/qap/layout/` `src/qap/passes.py` | `python -m unittest tests.test_layout` |
| `src/qap/search.py` `src/qap/web/fuzzy.js` | `python -m unittest tests.test_search` |
| `src/qap/plugin.py` `src/qap/plugins.py` `src/qap/plugin_cli.py` | `python -m unittest tests.test_plugins` |
| `src/qap/server.py` `src/qap/cli.py` `src/qap/snapshot.py` | `python -m unittest tests.test_cli_server tests.test_snapshot` |
| `src/qap/core_plugins/git-storage/` | `python -m unittest tests.test_git_storage` |
| `skill/scripts/build.py` | `python -m unittest tests.test_build` |
| `skill/scripts/carry.py` `skill/scripts/check.py` `skill/scripts/html_span.py` `src/qap/skill.py` | `python -m unittest tests.test_pages` |
| `docs/map.md` | `python -m unittest tests.test_map` |
