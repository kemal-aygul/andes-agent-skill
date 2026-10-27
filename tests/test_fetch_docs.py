from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_andes_docs as fetch


class FetchDocsTests(unittest.TestCase):
    def test_notebook_to_markdown_keeps_cells_and_drops_outputs(self) -> None:
        notebook = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Title\n", "text"]},
                {"cell_type": "code", "source": "ss.PFlow.run()", "outputs": [{"text": "SECRET OUTPUT"}]},
                {"cell_type": "code", "source": "   "},
            ]
        }
        text = fetch.notebook_to_markdown(notebook, "x.ipynb")
        self.assertIn("# Title", text)
        self.assertIn("```python\nss.PFlow.run()\n```", text)
        self.assertNotIn("SECRET OUTPUT", text)

    def test_member_filter_keeps_docs_and_license_only(self) -> None:
        keep = fetch._safe_member_path("andes-2.0.0/docs/source/tutorials/a.md", "docs/source/")
        self.assertEqual("docs/source/tutorials/a.md", keep.as_posix())
        self.assertEqual("LICENSE", fetch._safe_member_path("andes-2.0.0/LICENSE", "docs/source/").as_posix())
        for name in (
            "andes-2.0.0/andes/system.py",
            "andes-2.0.0/docs/source/../../evil.py",
            r"andes-2.0.0/docs/source/..\..\..\evil.md",
            "/abs/docs/source/x.md",
            "README.md",
        ):
            self.assertIsNone(fetch._safe_member_path(name, "docs/source/"), name)

    def test_force_refuses_a_folder_that_is_not_a_docs_cache(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            target = Path(tmp) / "mine"
            target.mkdir()
            (target / "keep.txt").write_text("keep")
            with self.assertRaises(SystemExit):
                fetch.fetch("v2.0.0", target, force=True)
            self.assertTrue((target / "keep.txt").is_file())

    def test_refuses_home_as_destination(self) -> None:
        with self.assertRaises(SystemExit):
            fetch.fetch("v2.0.0", Path.home(), force=True)


if __name__ == "__main__":
    unittest.main()
