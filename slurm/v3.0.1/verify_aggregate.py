"""Verify populated aggregate sections without requiring their source files."""

import argparse
import json
import math
from pathlib import Path


SECTIONS = ("runAssessor", "organism_identification.results", "modification_site_fractions")
PLACEHOLDERS = {"", "unknown", "none", "null", "n/a", "na", "undetermined",
                "not available", "not applicable", "skipped"}


def informative(value):
    if isinstance(value, dict):
        return any(informative(item) for key, item in value.items()
                   if key not in {"status", "reason", "file_path", "filename", "path",
                                  "accession", "category", "rank", "version"})
    if isinstance(value, list):
        return any(informative(item) for item in value)
    if isinstance(value, str):
        return value.strip().lower() not in PLACEHOLDERS
    return finite_number(value) and value > 0


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def organism_populated(results):
    if not isinstance(results, list):
        return False
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            continue
        for row in result["data"]:
            if not isinstance(row, dict):
                continue
            taxid = row.get("taxon_id")
            valid_taxid = (isinstance(taxid, int) and not isinstance(taxid, bool) and taxid > 0) or (
                isinstance(taxid, str) and taxid.isdigit() and int(taxid) > 0)
            if valid_taxid and finite_number(row.get("score")) and row["score"] >= 0:
                return True
    return False


def modifications_populated(value):
    if isinstance(value, dict):
        rows = value.get("data")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                identified = any(informative(row.get(key)) for key in ("mod_key", "unimod_id", "mod_name", "mass_shift"))
                fraction, potential = row.get("fraction_modified"), row.get("potential_sites")
                if identified and finite_number(fraction) and 0 <= fraction <= 1 and (
                        potential is None or finite_number(potential) and potential > 0):
                    return True
        return any(modifications_populated(item) for key, item in value.items()
                   if key not in ("data", "summary"))
    if isinstance(value, list):
        return any(modifications_populated(item) for item in value)
    return False


def section_flags(data, pxd):
    if not isinstance(data, dict) or data.get("pxd_id") not in (None, pxd):
        raise ValueError(f"Invalid aggregate or PXD mismatch for {pxd}")
    assessor = data.get("runAssessor")
    files = assessor.get("files") if isinstance(assessor, dict) else None
    organism = data.get("organism_identification")
    return dict(zip(SECTIONS, (
        isinstance(files, dict) and any(isinstance(record, dict) and informative(record) for record in files.values()),
        organism_populated(organism.get("results")) if isinstance(organism, dict) else False,
        modifications_populated(data.get("modification_site_fractions")),
    )))


def verify(path, pxd, required):
    with Path(path).open() as handle:
        flags = section_flags(json.load(handle), pxd)
    missing = [section for section in required if not flags[section]]
    if missing:
        raise ValueError(f"{path}: missing populated sections: {', '.join(missing)}")
    return flags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("--pxd", required=True)
    parser.add_argument("--require", nargs="+", choices=SECTIONS, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.aggregate, args.pxd, args.require), sort_keys=True))


if __name__ == "__main__":
    main()
