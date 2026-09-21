"""Focused tests for safe application of SDRF refinement overrides."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

from finalize_sdrf import _build_applied_overrides


class FinalizeOverridesTest(unittest.TestCase):
    def test_blocks_additive_cell_line_override(self) -> None:
        overrides, metrics = _build_applied_overrides({
            "field_overrides": {
                "cell_line": {
                    "builder_field": "cell_line",
                    "pipeline_values": ["HAP1"],
                    "selected_value": "HAP1, HeLa",
                    "apply_override": True,
                }
            }
        })

        self.assertNotIn("cell_line", overrides)
        self.assertEqual(metrics["cell_line_additive_overrides_blocked"], 1)

    def test_allows_replacement_cell_line_override(self) -> None:
        overrides, metrics = _build_applied_overrides({
            "field_overrides": {
                "cell_line": {
                    "builder_field": "cell_line",
                    "pipeline_values": ["HeLa"],
                    "selected_value": "HAP1",
                    "apply_override": True,
                }
            }
        })

        self.assertEqual(overrides["cell_line"], "HAP1")
        self.assertEqual(metrics["cell_line_additive_overrides_blocked"], 0)