from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from andes_workflow import build_parser, parse_atom


class CliHelperTests(unittest.TestCase):
    def test_parse_atom(self) -> None:
        self.assertEqual(parse_atom("2"), 2)
        self.assertEqual(parse_atom("2.5"), 2.5)
        self.assertEqual(parse_atom("Line_5"), "Line_5")
        self.assertEqual(parse_atom("true"), True)
        self.assertEqual(parse_atom('[1,2]'), '[1,2]')

    def test_parser_has_commands(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "study.json"])
        self.assertEqual(args.command, "validate")


if __name__ == "__main__":
    unittest.main()
