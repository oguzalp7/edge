#!/usr/bin/env python3
"""
Unit Tests for QA Fiber Inspector & Component Locator.
"""

import unittest
from unittest.mock import patch, MagicMock
import tempfile
import json
from pathlib import Path
import sys

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.brigade import qa_fiber


class TestQAFiber(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.src_dir = self.repo_path / "src" / "components"
        self.src_dir.mkdir(parents=True, exist_ok=True)

        # Create a sample React component file
        self.component_code = """import React from 'react';

export interface SampleCardProps {
  title: string;
}

export function SampleCard({ title }: SampleCardProps) {
  return (
    <div className="card-container">
      <h2>{title}</h2>
      <button className="confirm-btn">
        Onayla ve Devam Et
      </button>
    </div>
  );
}
"""
        self.sample_file = self.src_dir / "SampleCard.tsx"
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write(self.component_code)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_locate_component_in_repo_success(self):
        loc = qa_fiber.locate_component_in_repo(
            repo_path=self.repo_path,
            component_name="SampleCard",
            element_text="Onayla ve Devam Et"
        )
        self.assertIsNotNone(loc)
        self.assertEqual(loc["component"], "SampleCard")
        self.assertEqual(loc["file"], "src/components/SampleCard.tsx")
        # Line 12 is where 'Onayla ve Devam Et' resides
        self.assertEqual(loc["line"], 12)

    def test_locate_component_fallback_to_def_line(self):
        loc = qa_fiber.locate_component_in_repo(
            repo_path=self.repo_path,
            component_name="SampleCard",
            element_text="NonExistentText"
        )
        self.assertIsNotNone(loc)
        # Definition line is line 7
        self.assertEqual(loc["line"], 7)

    def test_locate_nonexistent_component(self):
        loc = qa_fiber.locate_component_in_repo(
            repo_path=self.repo_path,
            component_name="MissingWidget"
        )
        self.assertIsNone(loc)

    @patch("tools.brigade.qa_fiber.subprocess.run")
    def test_stage_to_frontier_cli(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        res = qa_fiber.stage_to_frontier(
            repo_path=self.repo_path,
            file_path="src/components/SampleCard.tsx",
            line_number=11,
            component="SampleCard",
            issue="Metin butondan taştı",
            category="overflow"
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["method"], "frontier-axi CLI")
        self.assertIn("src/components/SampleCard.tsx:11", res["title"])
        self.assertIn("Metin butondan taştı", res["title"])
        self.assertIn("(#overflow)", res["title"])

    def test_stage_to_frontier_file_fallback(self):
        # Force FileNotFoundError on subprocess to test direct .frontier.toml fallback
        with patch("tools.brigade.qa_fiber.subprocess.run", side_effect=FileNotFoundError):
            res = qa_fiber.stage_to_frontier(
                repo_path=self.repo_path,
                file_path="src/components/SampleCard.tsx",
                line_number=11,
                component="SampleCard",
                issue="Font boyutu okunamıyor",
                category="contrast"
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "Direct .frontier.toml append")
            frontier_file = self.repo_path / ".frontier.toml"
            self.assertTrue(frontier_file.exists())
            content = frontier_file.read_text(encoding="utf-8")
            self.assertIn("[[frontiers]]", content)
            self.assertIn("src/components/SampleCard.tsx:11", content)
            self.assertIn("(#contrast)", content)

    @patch("tools.brigade.qa_fiber.execute_browser_eval")
    def test_inspect_fiber_hierarchy_filtering(self, mock_eval):
        mock_eval.return_value = {
            "success": True,
            "tag": "BUTTON",
            "text": "Onayla ve Devam Et",
            "classes": "confirm-btn",
            "hierarchy": [
                "button",
                "LinkComponent",
                "SampleCard",
                "LayoutRouter",
                "AppRouter",
                "Root"
            ],
            "debugSource": None
        }

        res = qa_fiber.inspect_fiber(
            query="button.confirm-btn",
            repo_path_str=str(self.repo_path)
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["component"], "SampleCard")
        # Internal wrappers and lowercase tags should be filtered out
        self.assertEqual(res["hierarchy"], ["SampleCard"])
        self.assertIsNotNone(res["location"])
        self.assertEqual(res["location"]["file"], "src/components/SampleCard.tsx")
        self.assertEqual(res["location"]["line"], 12)


if __name__ == "__main__":
    unittest.main()
