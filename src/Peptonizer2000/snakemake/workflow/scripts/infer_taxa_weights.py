import argparse
import gzip
import json

from peptonizer.peptonizer import perform_taxa_weighing, parse_peptide_tsv, UnipeptCommunicator

parser = argparse.ArgumentParser()

parser.add_argument(
    "--number-of-taxa",
    type=int,
    required=True,
    help="Number of taxa to include in the final Peptonizer2000 output.",
)
parser.add_argument(
    "--sequence-scores-dataframe-file",
    type=str,
    required=False,
    help="Output: path to a CSV-file that will contain all computed sequence scores.",
)
parser.add_argument(
    "--taxa-weights-dataframe-file",
    type=str,
    required=False,
    help="Output: path to a CSV-file that will contain all computed taxa weights.",
)
parser.add_argument(
    "--unipept-response-file",
    type=str,
    required=True,
)
parser.add_argument(
    "--taxon-rank",
    type=str,
    required=False,
    default="species",
    help="Taxonomic rank at which you want the Peptonizer2000 results to be resolved.",
)
parser.add_argument(
    "--pout-file",
    type=str,
    required=True,
    help="Input: path to percolator (ms2rescore) '.pout' file.",
)

args = parser.parse_args()

with open(args.pout_file, 'rt', encoding='utf-8') as file:
    file_contents = file.read()

# Parse the input MS2Rescore file
pep_score, pep_psm_counts = parse_peptide_tsv(file_contents)


# Parse the Unipept response file
with open(args.unipept_response_file, "r") as file:
    unipept_responses = json.load(file)

df, weights = perform_taxa_weighing(
    unipept_responses,
    pep_score,
    pep_psm_counts,
    args.number_of_taxa,
    UnipeptCommunicator(),
    args.taxon_rank
)

print("Started dumping produced results to CSV-files...")
df.to_csv(args.sequence_scores_dataframe_file)
weights.to_csv(args.taxa_weights_dataframe_file)
