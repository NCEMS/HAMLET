import sys
import shutil
from pathlib import Path

def safe_copytree(src, dst):
    """Copy tree, removing destination if it exists."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

if len(sys.argv) != 3:
    print("Usage: python updatestore.py <results_path> <store_path>")
    sys.exit(1)

results_path = Path(sys.argv[1])
store_path = Path(sys.argv[2])

for pxd_dir in results_path.glob("PXD*"):
    pxd = pxd_dir.name
    print(f"Processing {pxd}...")
    
    # (1) Copy aggregated_results.json
    agg = pxd_dir / f"{pxd}_aggregated_results.json"
    if agg.exists():
        shutil.copy2(agg, store_path / "aggregated_results_files")
        print(f"  ✓ Copied aggregated_results.json")
    else:
        print(f"  ✗ aggregated_results.json not found")
    
    # (2) Copy metadata_extraction_output contents
    meta = pxd_dir / "agentic_metadata" / "metadata_extraction_output"
    if meta.exists():
        for item in meta.iterdir():
            if item.is_dir():
                safe_copytree(item, store_path / "agentic_results_files" / pxd / item.name)
        print(f"  ✓ Copied metadata_extraction_output contents")
    else:
        print(f"  ✗ metadata_extraction_output not found")
    
    # (3) If post_judge/json_outputs empty, copy judge_output
    post_judge_outputs = meta / "post_judge" / "json_outputs"
    if post_judge_outputs.exists() and not any(post_judge_outputs.iterdir()):
        judge = pxd_dir / "judge_output"
        if judge.exists():
            safe_copytree(judge, store_path / "agentic_results_files" / pxd / "judge_output")
            print(f"  ✓ post_judge/json_outputs empty, copied judge_output")
        else:
            print(f"  ✗ post_judge/json_outputs empty but judge_output not found")
    elif post_judge_outputs.exists():
        print(f"  ℹ post_judge/json_outputs has content, skipping judge_output")


    # (4) copy /scratch/ims86/HAMLETruns/HAMLET_0/results/PXD000070/agentic_metadata/PXD000070.sdrf.tsv
    sdrf = pxd_dir / "agentic_metadata" / f"{pxd}.sdrf.tsv"
    if sdrf.exists() and sum(1 for _ in sdrf.open()) > 1:
        shutil.copy2(sdrf, store_path / "agentic_results_files" / pxd / f"{pxd}.sdrf.tsv")
        print(f"  ✓ Copied {pxd}.sdrf.tsv")
    elif sdrf.exists():
        print(f"  ℹ {pxd}.sdrf.tsv contains only a header, skipping")
    else:
        print(f"  ✗ {pxd}.sdrf.tsv not found")
        
print("\nDone!")


