import sys
import shutil
from pathlib import Path


def replace_agentic_store(agentic_metadata, judge_output, destination):
    """Replace a PXD's store output with the current agentic result schema."""
    staging = destination.with_name(f".{destination.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    if agentic_metadata.exists():
        shutil.copytree(agentic_metadata, staging)
    else:
        staging.mkdir()
    if judge_output.exists():
        shutil.copytree(judge_output, staging / "judge_output")
    if destination.exists():
        shutil.rmtree(destination)
    staging.rename(destination)


if len(sys.argv) != 3:
    print("Usage: python updatestore.py <results_path> <store_path>")
    sys.exit(1)

results_path = Path(sys.argv[1])
store_path = Path(sys.argv[2])

for pxd_dir in results_path.glob("PXD*"):
    pxd = pxd_dir.name
    agentic_store_dir = store_path / "agentic_results_files" / pxd
    print(f"Processing {pxd}...")
    
    # (1) Copy aggregated_results.json
    agg = pxd_dir / f"{pxd}_aggregated_results.json"
    if agg.exists():
        shutil.copy2(agg, store_path / "aggregated_results_files")
        print(f"  ✓ Copied aggregated_results.json")
    else:
        print(f"  ✗ aggregated_results.json not found")
    
    # (2) Replace the entire agentic output with the current schema. This avoids
    # retaining legacy flat directories alongside current nested stage outputs.
    agentic_metadata = pxd_dir / "agentic_metadata"
    judge = pxd_dir / "judge_output"
    if agentic_metadata.exists() or judge.exists():
        replace_agentic_store(agentic_metadata, judge, agentic_store_dir)
        print("  ✓ Replaced agentic output with current schema")
    else:
        print("  ✗ agentic_metadata and judge_output not found")
        
print("\nDone!")


