# Changelog

## 1.0.0-rc.2 — hardened application candidate

- Hardened file traversal to avoid following symbolic links, including linked directories.
- Added cancellable duplicate hashing in a background thread so the UI stays responsive.
- Persisted the last selected folder, recursive scan preference, and window geometry.
- Added File and Help menus with an About dialog.
- Made report export use an atomic temporary-file replacement.
- Added defensive validation for sort plans and operation journal records.\n- Added regression tests for symlinked directories, external source paths, and destination collisions.
- Expanded file-type categories and preserved preview-before-move workflow.
- Kept duplicate detection non-destructive: it reports matches and never deletes files.

## 1.0.0-rc.1

- Added atomic configuration/history writes, safer scan behavior, and Windows CI build workflow.
