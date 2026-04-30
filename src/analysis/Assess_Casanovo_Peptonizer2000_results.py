import os
import pandas as pd
from glob import glob

# (1) Read in the ground truth CSV
ground_truth_df = pd.read_csv('data/BigBio_taxids_df.csv')
print(ground_truth_df)

# (2) Get unique (PXD, parent-taxid) pairs
ground_truth_pairs = ground_truth_df[['PXD', 'parent-taxid']].drop_duplicates()
ground_truth_dict = dict(zip(ground_truth_pairs['PXD'], ground_truth_pairs['parent-taxid']))
print(ground_truth_dict)
valid_taxids = [str(s) for s in ground_truth_dict.values()]
print(f'Valid taxids: {valid_taxids} {len(valid_taxids)}')

# (3) Find all peptonizer_result.csv files
search_dir = '/home/ians/Local-Intelligent-metadata-compilation/output/CasanovoSequence/PRIDE/'
result_files = [y for x in os.walk(search_dir) for y in glob(os.path.join(x[0], 'peptonizer_result.csv'))]

all_results = []
final_results = []
for file_path in result_files:
    print(f'Processing {file_path}')
 
    # (4) Extract PXD from file path
    parts = file_path.split(os.sep)
    try:
        pxd = next(part for part in parts if part.startswith('PXD'))
    except StopIteration:
        continue  # skip files not in expected structure
    
    # Load result file
    df = pd.read_csv(file_path)
    
    # (4a) Add 'hit' column
    df['hit'] = df['score'] > 0.95

    # (4b) Add 'assessment' column
    parent_taxid = ground_truth_dict.get(pxd)
    def assess(row):
        if parent_taxid is None:
            return 'Unknown'
        if row['taxon_id'] == parent_taxid and row['hit']:
            return 'TP'
        elif row['taxon_id'] != parent_taxid and not row['hit']:
            return 'TN'
        elif row['taxon_id'] != parent_taxid and row['hit']:
            return 'FP'
        elif row['taxon_id'] == parent_taxid and not row['hit']:
            return 'FN'
        return 'Unknown'
    df = df[df['taxon_id'].astype(str).isin(valid_taxids)]
    df['assessment'] = df.apply(assess, axis=1)
    df['PXD'] = pxd
    all_results.append(df)
    print(df)

    # calculate the recall, precision, f1 score using the assessment column
    tp = df[df['assessment'] == 'TP'].shape[0]
    tn = df[df['assessment'] == 'TN'].shape[0]
    fp = df[df['assessment'] == 'FP'].shape[0]
    fn = df[df['assessment'] == 'FN'].shape[0]

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    print({'PXD': pxd, 'parent_taxid': parent_taxid, 'precision': precision, 'recall': recall, 'f1': f1})

    # get the taxon_id with the highest probability
    if not df.empty:
        max_prob_row = df.loc[df['score'].idxmax()]
        final_results.append({'PXD': pxd, 'parent_taxid': parent_taxid, 'precision': precision, 'recall': recall, 'f1': f1, 'best_taxon_id': max_prob_row['taxon_id']})
    else:
        final_results.append({'PXD': pxd, 'parent_taxid': parent_taxid, 'precision': precision, 'recall': recall, 'f1': f1, 'best_taxon_id': None})


# Optionally, concatenate all results into one DataFrame
all_results_df = pd.concat(all_results, ignore_index=True)
final_results_df = pd.DataFrame(final_results)
print(final_results_df)

# Save or process final_df as needed
final_results_df.to_csv('output/Peptonizer2000_analysis/assessment_results.csv', index=False)
print(f'SAVED: output/Peptonizer2000_analysis/assessment_results.csv')

# make a scatter plot of parent_taxid vs best_taxon_id colored by the f1 score
import matplotlib.pyplot as plt

# Convert string taxids to categorical codes for plotting

# Use the union of all taxids for consistent axis order
all_taxids = pd.Series(list(final_results_df['parent_taxid'].astype(str)) + list(final_results_df['best_taxon_id'].astype(str))).unique()
all_taxids_sorted = sorted(all_taxids)

parent_taxids = pd.Categorical(final_results_df['parent_taxid'].astype(str), categories=all_taxids_sorted, ordered=True)
best_taxon_ids = pd.Categorical(final_results_df['best_taxon_id'].astype(str), categories=all_taxids_sorted, ordered=True)

parent_taxid_codes = parent_taxids.codes
best_taxon_id_codes = best_taxon_ids.codes
taxid_labels = all_taxids_sorted

plt.figure(figsize=(12, 8))
scatter = plt.scatter(parent_taxid_codes, best_taxon_id_codes, c=final_results_df['f1'], cmap='viridis', alpha=0.7, marker='o', s=100)
plt.colorbar(scatter, label='F1 Score')
plt.xlabel('Parent Tax ID')
plt.ylabel('Best Taxon ID')
plt.title('Parent Tax ID vs Best Taxon ID Colored by F1 Score')
plt.grid(True)

# Set x/y ticks to show the string labels in the same order
plt.xticks(ticks=range(len(taxid_labels)), labels=taxid_labels, rotation=90)
plt.yticks(ticks=range(len(taxid_labels)), labels=taxid_labels)

# Add diagonal line for correct predictions
plt.plot(range(len(taxid_labels)), range(len(taxid_labels)), color='red', linestyle='--', linewidth=1, label='Correct Prediction Diagonal')
plt.legend()

plt.tight_layout()
plt.savefig('output/Peptonizer2000_analysis/scatter_plot.png')
print(f'SAVED: output/Peptonizer2000_analysis/scatter_plot.png')

nmatched = final_results_df[final_results_df['parent_taxid'] == final_results_df['best_taxon_id']].shape[0]
ntotal = final_results_df.shape[0]
print(f'Matched: {nmatched}, Total: {ntotal}, Accuracy: {nmatched / ntotal if ntotal > 0 else 0}')