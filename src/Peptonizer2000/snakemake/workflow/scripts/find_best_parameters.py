import argparse
import os
import pandas as pd
import re
import shutil
from os import path

from peptonizer.peptonizer import find_best_parameters, ParameterSet, clean_csv, parse_taxon_scores

parser = argparse.ArgumentParser()


parser.add_argument(
    "--taxa-weights-dataframe-file",
    type=str,
    required=True,
    help="Input: path to a CSV-file that contains all computed taxa weights.",
)
parser.add_argument(
    "--results-folder",
    type=str,
    required=True,
    help="Path to a folder containing CSV-files with all the results from a prior PepGM analysis.",
)
parser.add_argument(
    "--best-params-file",
    type=str,
    required=True,
    help="Path to the output file where the best suited parameter set should be stored in."
)
parser.add_argument(
    "--best-params-csv",
    type=str,
    required=True,
    help="Path to the output file where the results of the best Peptonizer run in CSV format should be stored."
)
parser.add_argument(
    "--best-params-png",
    type=str,
    required=True,
    help="Path to the output file where the results of the best Peptonizer run in PNG format should be stored."
)

args = parser.parse_args()

def find_csv_files(folder_path):
    csv_files = []

    # Walk through the directory and subdirectories
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.csv') and file.find("pepgm_results") >= 0:
                csv_files.append(os.path.join(root, file))

    return csv_files

def extract_parameters(filename):
    # Regular expression to find the patterns 'aX', 'bX', 'pX' where X is a float
    pattern = r'_a([0-9.]+)_b([0-9.]+)_p([0-9.]+)\.'

    match = re.search(pattern, filename)

    if match:
        a = float(match.group(1))
        b = float(match.group(2))
        p = float(match.group(3))
        return a, b, p
    else:
        raise ValueError("The filename does not contain valid 'a', 'b', and 'p' parameters.")

# Get all the taxa weights that are required to compute the goodness metric for each results file
weights_df = pd.read_csv(
    args.taxa_weights_dataframe_file,
    usecols = ['HigherTaxa', 'scaled_weight']
)

# Store all result dataframes and the corresponding parameter sets in this list that will be used to finally find the
# best parameter set.
results_and_params = []
for result_file in find_csv_files(args.results_folder):
    alpha, beta, prior = extract_parameters(result_file)
    with open(result_file, "r") as f:
        taxon_scores = parse_taxon_scores(f.read())
        parameter_set = ParameterSet(alpha, beta, prior)
        results_and_params.append((taxon_scores, parameter_set))

best_param_set = find_best_parameters(results_and_params, weights_df)

# Write out the best parameters to a CSV file for future reference
with open(args.best_params_file, "w") as f:
    f.write("alpha,beta,prior\n")
    f.write(f"{best_param_set.alpha},{best_param_set.beta},{best_param_set.prior}\n")

# Clean the CSV for the best parameters and write it to the final output directory
best_csv_path = path.join(args.results_folder, f"prior{best_param_set.prior}", f"pepgm_results_a{best_param_set.alpha}_b{best_param_set.beta}_p{best_param_set.prior}.csv")
with open(best_csv_path, "r") as in_file:
    clean_taxa_csv = clean_csv(in_file.read())

    with open(args.best_params_csv, "w") as out_file:
        out_file.write(clean_taxa_csv)

# Copy the plots with the best parameters to the final output directory
shutil.copy(
    path.join(args.results_folder, f"prior{best_param_set.prior}", f"pepgm_results_a{best_param_set.alpha}_b{best_param_set.beta}_p{best_param_set.prior}.png"),
    args.best_params_png
)
