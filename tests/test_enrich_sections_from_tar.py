import csv
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "src/python/enrich_sections_from_tar.py"
SPEC = importlib.util.spec_from_file_location("enrich_sections_from_tar", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_tar(path, entries, mode="w:gz"):
    with tarfile.open(str(path), mode) as archive:
        for name, data, mtime in entries:
            content = data if isinstance(data, bytes) else json.dumps(data).encode()
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mtime = mtime
            archive.addfile(member, io.BytesIO(content))


class ArchiveSectionsTests(unittest.TestCase):
    def test_merge_parallel_selection_and_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "PXD000001_aggregated_results.json"
            baseline.write_text(json.dumps({"runAssessor": {"files": [1]}, "padding": "x" * 400}))
            os.utime(str(baseline), (100, 100))
            source = root / "input.csv"
            columns = ["accession", "original"] + list(MODULE.SECTIONS) + [MODULE.PATH_COLUMN]
            rows = [
                dict(accession="PXD000001", original="comma, and\nnewline",
                     **{MODULE.PATH_COLUMN: str(baseline)}),
                dict(accession="PXD000002", original="second"),
                dict(accession="PXD000003", original="unmatched"),
            ]
            with source.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            name1 = "HAMLET/results/PXD000001/PXD000001_aggregated_results.json"
            name2 = "HAMLET/store/PXD000002/PXD000002_aggregated_results.json"
            archive1 = root / "cpu.tar.gz"
            archive2 = root / "store.tar.gz"
            old = {"runAssessor": {"x": 1}, "organism_identification": {"results": []}}
            new = {"runAssessor": {"x": 1}, "organism_identification": {"results": [1]}}
            # Pad to identical sizes, so mtime must select the newer JSON.
            old["padding"] = "x"
            new["padding"] = ""
            self.assertEqual(len(json.dumps(old)), len(json.dumps(new)))
            make_tar(archive1, [(name1, new, 999), (name2, old, 100)])
            make_tar(archive2, [(name2, new, 200)])
            lists = []
            for number, names in enumerate(([name1, name2], [name2])):
                listing = root / ("list{}.txt".format(number))
                listing.write_text("\n".join("/scratch/cluster/" + name for name in names))
                lists.append(listing)
            output = root / "output.csv"
            result = MODULE.enrich(source, output,
                                   [(archive1, lists[0]), (archive2, lists[1])], 2)
            self.assertEqual(result[0][MODULE.PATH_COLUMN], str(baseline))
            self.assertEqual(result[1]["organism_identification.results"], "True")
            self.assertTrue(result[1][MODULE.PATH_COLUMN].startswith(str(archive2) + "::"))
            self.assertEqual(result[2][MODULE.PATH_COLUMN], "")
            self.assertEqual([row["original"] for row in result],
                             [row["original"] for row in rows])
            with self.assertRaises(FileExistsError):
                MODULE.enrich(source, output, [(archive1, lists[0])], 1)

    def test_largest_beats_newer_and_basename_does_not_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "HAMLET/results/PXD000001/PXD000001_aggregated_results.json"
            large = {"runAssessor": {"padding": "x" * 100}}
            small = {"runAssessor": {}}
            archive = root / "archive.tar"
            make_tar(archive, [(name, large, 1), (name, small, 999),
                              ("HAMLET/work/PXD000001_aggregated_results.json", large, 999)], "w")
            listing = root / "list.txt"
            listing.write_text("/scratch/HAMLET/" + name[len("HAMLET/"):])
            selected = MODULE.scan_archive((str(archive), str(listing), {"PXD000001"}, {}))
            self.assertEqual(selected["PXD000001"][1]["runAssessor"], "True")
            self.assertEqual(selected["PXD000001"][0][1], 1000000000)

    def test_invalid_selected_json_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "HAMLET/store/PXD000001_aggregated_results.json"
            archive = root / "bad.tar.gz"
            make_tar(archive, [(name, b"{broken", 1)])
            listing = root / "list.txt"
            listing.write_text(name)
            with self.assertRaises(ValueError):
                MODULE.scan_archive((str(archive), str(listing), {"PXD000001"}, {}))

    def test_larger_archive_copy_beats_newer_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "HAMLET/store/PXD000001_aggregated_results.json"
            archive = root / "archive.tar.gz"
            make_tar(archive, [(name, {"runAssessor": {"padding": "x" * 100}}, 1)])
            listing = root / "list.txt"
            listing.write_text(name)
            selected = MODULE.scan_archive((
                str(archive), str(listing), {"PXD000001"},
                {"PXD000001": (10, 999000000000, "ROAR")},
            ))
            self.assertGreater(selected["PXD000001"][0][0], 10)
            self.assertEqual(selected["PXD000001"][1]["runAssessor"], "True")

    def test_zstandard_archive(self):
        import zstandard

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "HAMLET/store/intermediate_files/PXD000001/PXD000001_aggregated_results.json"
            plain = root / "archive.tar"
            make_tar(plain, [(name, {"modification_site_fractions": {"data": [1]}}, 1)], "w")
            archive = root / "archive.tar.zst"
            archive.write_bytes(zstandard.ZstdCompressor().compress(plain.read_bytes()))
            listing = root / "list.txt"
            listing.write_text("/scratch/ims86/HAMLET_CyVerse/" + name[len("HAMLET/"):])
            selected = MODULE.scan_archive((str(archive), str(listing), {"PXD000001"}, {}))
            self.assertEqual(selected["PXD000001"][1]["modification_site_fractions"], "True")


if __name__ == "__main__":
    unittest.main()
