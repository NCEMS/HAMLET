import sys
import shutil
import pandas as pd
from pathlib import Path

def safe_copytree(src, dst):
    """Copy tree, removing destination if it exists."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

if len(sys.argv) != 3:
    print("Usage: python updatemaster.py <master_path> <store_path>")
    sys.exit(1)

master_file = sys.argv[1] # .csv file
store_path = Path(sys.argv[2])

master = pd.read_csv(master_file)
print(master)

# check if master has the following columns HAMLETmeti, HAMLETmeta, HAMLETjudge
required_columns = ['HAMLETmeti', 'HAMLETmeta', 'HAMLETjudge']
for col in required_columns:
    if col not in master.columns:
        # add it
        master[col] = False
        print(f"Added column {col} to master == False")


## Filter master to have those with pmc_id not null
# master = master[master['pmc_id'].notnull()]
## Filter mster to those with a raw_file_count > 0
# master = master[master['raw_file_count'] > 0]
# quit()

for rowi, row in master.iterrows():
    pxd = row['accession']
    meti_results = False
    meta_results = False
    judge_accuracy = False

    ## Check if there is a store/aggregated_results_files/PXD#######_aggregated_results.json file and set meti_results = True if it exists, False if not
    meti_results = (store_path / "aggregated_results_files" / f"{pxd}_aggregated_results.json").exists()
    if meti_results:
        print(f"{pxd} has aggregated_results.json")
    else:
        print(f"{pxd} does not have aggregated_results.json")
    master.at[rowi, 'HAMLETmeti'] = meti_results

    ## Check if there is a store/agentic_results_files/PXD#######/ directory and set meta_results = True if it exists, False if not
    meta_results = (store_path / "agentic_results_files" / pxd ).exists()
    if meta_results:
        print(f"{pxd} has metadata_extraction_output")
    else:
        print(f"{pxd} does not have metadata_extraction_output")
    master.at[rowi, 'HAMLETmeta'] = meta_results
    
    ## Check if there is a store/agentic_results_files/PXD#######/post_judge/llm_judge_per_paper.csv file and set judge_accuracy = True if it exists, False if not
    judge_accuracy = (store_path / "agentic_results_files" / pxd / "post_judge" / "llm_judge_per_paper.csv").exists()
    if judge_accuracy:
        print(f"{pxd} has llm_judge_per_paper.csv")
    else:
        print(f"{pxd} does not have llm_judge_per_paper.csv")
    master.at[rowi, 'HAMLETjudge'] = judge_accuracy

print(master)
master = master.sort_values(by=['HAMLETmeti', 'HAMLETmeta', 'HAMLETjudge'], ascending=[False, False, False])
print(master)
print(master[['HAMLETmeti', 'HAMLETmeta', 'HAMLETjudge']].describe())

## Update sets of pxds list in assets/pxd_lists/nextUp where we chunk the PXDs where HAMLETmeti == False into N list of size 10 each 
pxds_meti = master[master['HAMLETmeti'] == False]['accession'].tolist()
pxds_meta = master[master['HAMLETmeta'] == False]['accession'].tolist()
pxds_judge = master[master['HAMLETjudge'] == False]['accession'].tolist()
print(f"PXDs with HAMLETmeti == False: {pxds_meti}")
print(f"PXDs with HAMLETmeta == False: {pxds_meta}")
print(f"PXDs with HAMLETjudge == False: {pxds_judge}")  
k = 10
for i in range(0, len(pxds_meti), k):
    chunk = pxds_meti[i:i + k]
    with open(f"assets/pxd_lists/nextUp/pxds_meti_{i//k}.txt", "w") as f:
        f.write(f"PXDs\n")
        for pxd in chunk:
            f.write(f"{pxd}\n")
    print(f"Wrote {len(chunk)} PXDs to assets/pxd_lists/nextUp/pxds_meti_{i//k}.txt")

master.to_csv(master_file, index=False)
print(f"Updated master file {master_file} with HAMLETmeti, HAMLETmeta, HAMLETjudge columns")

print("\nDone!")


