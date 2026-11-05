import math
import os
import shutil
import unittest

from referee.changes import changed_lines, overlaps
from referee.errors import RefereeError
from tests.helpers import commit_all, git, init_repo, lines, write


class ChangedLines(unittest.TestCase):
    def repo(self, files):
        root = init_repo(files)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_uncommitted_edit(self):
        root = self.repo({"a.go": lines(10)})
        write(root, "a.go", lines(10).replace("line 4\n", "CHANGED\n"))
        self.assertEqual(changed_lines("main", root), {"a.go": [(4, 4)]})

    def test_multi_line_hunk_and_second_hunk(self):
        root = self.repo({"a.go": lines(20)})
        text = lines(20).replace("line 3\nline 4\nline 5\n", "X\nY\nZ\n").replace("line 15\n", "W\n")
        write(root, "a.go", text)
        self.assertEqual(changed_lines("main", root), {"a.go": [(3, 5), (15, 15)]})

    def test_new_untracked_file_is_all_changed(self):
        root = self.repo({"a.go": lines(3)})
        write(root, "pkg/new.go", lines(3))
        result = changed_lines("main", root)
        self.assertEqual(result, {"pkg/new.go": [(1, math.inf)]})
        self.assertTrue(overlaps(result["pkg/new.go"], 500, 600))

    def test_deletion_only_hunk(self):
        root = self.repo({"a.go": lines(5)})
        write(root, "a.go", lines(5).replace("line 3\n", ""))
        self.assertEqual(changed_lines("main", root), {"a.go": [(2, 3)]})

    def test_deleted_file_not_listed(self):
        root = self.repo({"a.go": lines(5), "b.go": lines(5)})
        os.remove(os.path.join(root, "b.go"))
        self.assertEqual(changed_lines("main", root), {})

    def test_crlf_only_difference_is_not_a_change(self):
        root = self.repo({"a.go": b"one\r\ntwo\r\nthree\r\nfour\r\n"})
        write(root, "a.go", b"one\ntwo\nTHREE\nfour\n")
        self.assertEqual(changed_lines("main", root), {"a.go": [(3, 3)]})

    def test_whole_file_line_ending_conversion_is_no_change(self):
        root = self.repo({"a.go": b"one\r\ntwo\r\n"})
        write(root, "a.go", b"one\ntwo\n")
        self.assertEqual(changed_lines("main", root), {})

    def test_committed_branch_change_plus_uncommitted(self):
        root = self.repo({"a.go": lines(10), "b.go": lines(10)})
        git(root, "checkout", "-q", "-b", "feature")
        write(root, "a.go", lines(10).replace("line 2\n", "X\n"))
        commit_all(root)
        write(root, "b.go", lines(10).replace("line 9\n", "Y\n"))
        self.assertEqual(changed_lines("main", root), {"a.go": [(2, 2)], "b.go": [(9, 9)]})

    def test_changes_merged_into_base_after_branching_are_ignored(self):
        root = self.repo({"a.go": lines(10), "b.go": lines(10)})
        git(root, "checkout", "-q", "-b", "feature")
        write(root, "a.go", lines(10).replace("line 2\n", "X\n"))
        commit_all(root)
        git(root, "checkout", "-q", "main")
        write(root, "b.go", lines(10).replace("line 7\n", "other person\n"))
        commit_all(root, "someone else")
        git(root, "checkout", "-q", "feature")
        self.assertEqual(changed_lines("main", root), {"a.go": [(2, 2)]})

    def test_unknown_base(self):
        root = self.repo({"a.go": lines(3)})
        with self.assertRaises(RefereeError) as cm:
            changed_lines("origin/main", root)
        self.assertIn("找不到 origin/main 和 HEAD 的分岔點", str(cm.exception))

    def test_overlaps(self):
        self.assertTrue(overlaps([(5, 7)], 7, 9))
        self.assertTrue(overlaps([(5, 7)], 1, 5))
        self.assertFalse(overlaps([(5, 7)], 8, 9))
        self.assertFalse(overlaps(None, 1, 9))


if __name__ == "__main__":
    unittest.main()
