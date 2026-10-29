"""The content tree: projects group the top-level folders; folders hold folders and subjects; a subject holds
its passes.

    <content_root>/
      projects.json             optional {default, projects: [{id, title, icon, color}]}
      <folder>/                 any depth; optional folder.json {title, icon, order, project}
        <subject>/              subject.json {title, icon, qa_project, sources, created}
          QA-PASS-1.src.html, QA-PASS-1.html, …, img/

A directory is a subject when it holds subject.json (or, without one, QA-PASS files: an "implicit" subject).
Every other visible directory is a folder. Paths in and out of this package are POSIX paths relative to the
content root ("coach/v3/interaction"); "" is the root itself.

Projects (work, personal, …) sit above the top-level folders (the "families"). A project is not a directory:
it is an entry of projects.json, and a top-level folder or subject joins it with "project": "<id>" in its own
manifest. One without that key belongs to the default project. Nothing moves on disk, so every path, link and
symlink stays valid; a tree without projects.json reads exactly as before. A project is named "@<id>" wherever
a path is expected ("@work"): '@' never starts a folder name, so the two cannot clash.

folder.json "order" is either a number (this folder's rank among its siblings) or a list of child names
(the order of this folder's children). Children not named in a list follow, folders first, then by title.

Every mutation the CLI and the dashboard make goes through the functions below (make_folder, make_subject,
move, set_meta, place, make_project, assign_project, remove_project), so both write the same manifests.

Where a change goes:
  paths.py      a legal path, and reading or writing one json file
  read.py       the tree, and finding a folder, subject or project by what someone typed
  write.py      create, move, place and remove folders and subjects
  project.py    projects.json: a project, the default, and which family is in it
"""
from __future__ import annotations

from .paths import (
    FOLDER_FILE, PROJECTS_FILE, PROJECT_ID, RESERVED, SEGMENT, SUBJECT_FILE, LayoutError, abs_path, clean_rel,
    is_subject_dir, pretty, read_json, rel_path, slug, write_json,
)
from .project import (
    assign_project, make_project, project_id, project_node, read_projects, remove_project, set_project_meta,
)
from .read import find_project, folder_node, folders, projects, resolve, subject_node, subjects, tree, walk
from .write import make_folder, make_subject, move, place, relink_sources, remove_folder, set_meta

__all__ = [
    "FOLDER_FILE", "PROJECTS_FILE", "PROJECT_ID", "RESERVED", "SEGMENT", "SUBJECT_FILE", "LayoutError",
    "abs_path", "assign_project", "clean_rel", "find_project", "folder_node", "folders", "is_subject_dir",
    "make_folder", "make_project", "make_subject", "move", "place", "pretty", "project_id", "project_node",
    "projects", "read_json", "read_projects", "rel_path", "relink_sources", "remove_folder", "remove_project",
    "resolve", "set_meta", "set_project_meta", "slug", "subject_node", "subjects", "tree", "walk", "write_json",
]
