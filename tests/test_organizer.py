import json
import tempfile
import unittest
from pathlib import Path

from filebutler.organizer import (
    apply_sort_plan, build_sort_plan, has_undo, undo_last_sort, unique_destination
)
from filebutler.rules import validate_rules
from filebutler.scanner import category_for, scan_folder

class OrganizerTests(unittest.TestCase):
    def test_category_detection_is_case_insensitive(self):
        self.assertEqual(category_for(Path("PHOTO.JPG")), "Images")
        self.assertEqual(category_for(Path("notes.pdf")), "Documents")
        self.assertEqual(category_for(Path("unknown.xyz")), "Other")

    def test_scan_and_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photo.jpg").write_bytes(b"image")
            (root / "notes.pdf").write_bytes(b"document")
            scanned = scan_folder(root)
            self.assertEqual(len(scanned), 2)
            plan = build_sort_plan(scanned, root, {".jpg": "Photos", ".pdf": "Paper"})
            self.assertEqual(len(plan), 2)
            destinations = {destination.parent.name for _, destination in plan}
            self.assertEqual(destinations, {"Photos", "Paper"})

    def test_plan_reserves_duplicate_names_without_looping_or_colliding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a"
            b = root / "b"
            a.mkdir()
            b.mkdir()
            first = a / "same.pdf"
            second = b / "same.pdf"
            first.write_text("a")
            second.write_text("b")
            plan = build_sort_plan(
                [{"path": first}, {"path": second}], root, {".pdf": "Documents"}
            )
            self.assertEqual(len(plan), 2)
            self.assertEqual(len({destination for _, destination in plan}), 2)
            self.assertEqual({destination.name for _, destination in plan},
                             {"same.pdf", "same (1).pdf"})

    def test_unique_destination_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "report.pdf"
            original.write_text("existing")
            candidate = unique_destination(original)
            self.assertEqual(candidate.name, "report (1).pdf")
            self.assertTrue(original.exists())

    def test_apply_and_undo_restores_files_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.json"
            source = root / "holiday.jpg"
            source.write_bytes(b"original image bytes")
            plan = [(source, root / "Images" / source.name)]
            moved = apply_sort_plan(plan, history)
            self.assertEqual(len(moved), 1)
            self.assertFalse(source.exists())
            self.assertTrue(has_undo(root, history))
            restored = undo_last_sort(root, history)
            self.assertEqual(len(restored), 1)
            self.assertEqual(source.read_bytes(), b"original image bytes")
            self.assertFalse((root / "Images" / source.name).exists())
            self.assertFalse(has_undo(root, history))

    def test_undo_refuses_to_overwrite_original_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.json"
            source = root / "notes.txt"
            source.write_text("first")
            apply_sort_plan([(source, root / "Documents" / source.name)], history)
            source.write_text("new file at original path")
            with self.assertRaises(FileExistsError):
                undo_last_sort(root, history)
            self.assertEqual(source.read_text(), "new file at original path")
            self.assertTrue((root / "Documents" / "notes.txt").exists())

    def test_undo_refuses_changed_moved_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.json"
            source = root / "notes.txt"
            source.write_text("first")
            apply_sort_plan([(source, root / "Documents" / source.name)], history)
            moved = root / "Documents" / "notes.txt"
            moved.write_text("modified externally")
            with self.assertRaises(ValueError):
                undo_last_sort(root, history)
            self.assertTrue(moved.exists())
            self.assertFalse(source.exists())

    def test_rules_validation(self):
        self.assertEqual(validate_rules({".psd": "Design"}), {".psd": "Design"})
        with self.assertRaises(ValueError):
            validate_rules({"psd": "Design"})
        with self.assertRaises(ValueError):
            validate_rules({".psd": "../outside"})


    def test_scan_can_be_cancelled(self):
        from filebutler.scanner import scan_folder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                (root / f"{index}.txt").write_text(str(index))
            calls = {"count": 0}
            def cancel():
                calls["count"] += 1
                return calls["count"] > 2
            result = scan_folder(root, cancel_check=cancel)
            self.assertLess(len(result), 5)

    def test_duplicate_detection_groups_identical_content(self):
        from filebutler.scanner import find_duplicates
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "a.bin", root / "b.bin"
            a.write_bytes(b"same bytes")
            b.write_bytes(b"same bytes")
            items = [{"path": a, "size": a.stat().st_size}, {"path": b, "size": b.stat().st_size}]
            groups = find_duplicates(items)
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(next(iter(groups.values()))), 2)

    def test_sort_plan_ignores_files_outside_selected_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "selected"
            root.mkdir()
            external = base / "outside.txt"
            external.write_text("keep")
            plan = build_sort_plan([{"path": external}], root, {".txt": "Documents"})
            self.assertEqual(plan, [])
            self.assertTrue(external.exists())

    def test_scan_skips_file_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "selected"
            root.mkdir()
            external = base / "outside.txt"
            external.write_text("keep")
            link = root / "linked.txt"
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are not available in this environment")
            results = scan_folder(root)
            self.assertEqual(results, [])
            self.assertTrue(external.exists())

    def test_history_write_is_valid_json_with_newline(self):
        from filebutler.organizer import _write_history, _read_history
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            expected = {"operations": []}
            _write_history(path, expected)
            self.assertTrue(path.read_bytes().endswith(b"\n"))
            self.assertEqual(_read_history(path), expected)


    def test_sort_plan_rejects_symlink_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "selected"
            root.mkdir()
            target = base / "outside.txt"
            target.write_text("keep")
            link = root / "linked.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are not available in this environment")
            plan = build_sort_plan([{"path": link}], root, {".txt": "Documents"})
            self.assertEqual(plan, [])
            self.assertEqual(target.read_text(), "keep")

    def test_apply_rejects_source_outside_destination_root(self):
        from filebutler.organizer import apply_sort_plan
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "selected"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("keep")
            with self.assertRaises(ValueError):
                apply_sort_plan([(outside, root / "Documents" / outside.name)], base / "history.json")
            self.assertTrue(outside.exists())

    def test_apply_rejects_duplicate_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.txt"
            b = root / "b.txt"
            a.write_text("a")
            b.write_text("b")
            destination = root / "Documents" / "same.txt"
            with self.assertRaises(ValueError):
                apply_sort_plan([(a, destination), (b, destination)], root / "history.json")
            self.assertTrue(a.exists())
            self.assertTrue(b.exists())

    def test_scanner_does_not_follow_symlinked_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "selected"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "private.txt").write_text("keep")
            link = root / "external-dir"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are not available in this environment")
            results = scan_folder(root, recursive=True)
            self.assertEqual(results, [])
            self.assertTrue((outside / "private.txt").exists())


    def test_undo_rejects_history_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "selected"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("keep")
            moved = root / "Documents" / "moved.txt"
            moved.parent.mkdir()
            moved.write_text("content")
            history = base / "history.json"
            history.write_text(json.dumps({
                "operations": [{
                    "state": "completed",
                    "moves": [{
                        "source": str(outside),
                        "destination": str(moved),
                        "sha256": __import__("hashlib").sha256(b"content").hexdigest(),
                        "undone": False,
                    }]
                }]
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                undo_last_sort(root, history)
            self.assertTrue(outside.exists())
            self.assertTrue(moved.exists())

if __name__ == "__main__":
    unittest.main()
