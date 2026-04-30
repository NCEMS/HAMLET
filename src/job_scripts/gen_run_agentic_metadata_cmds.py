import glob
import sys,os

files = glob.glob("/home/ians/git_repos/HAMLET/store/aggregated_results_files/PXD*_aggregated_results.json")
print(f'Found {len(files)} aggregated results files')
for f in files:
    pxd = os.path.basename(f).split("_")[0]
    cmd = f"python src/python/run_agentic_metadata.py --input {f} --outdir store/agentic_results_files/{pxd}/ > logs/{pxd}_agentic_metadata.log 2>&1"
    print(cmd)
