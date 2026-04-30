import argparse
import networkx as nx
import pandas as pd

from peptonizer.peptonizer import cluster_taxa_based_on_similarity

parser = argparse.ArgumentParser(description = 'cluster Taxa based on peptidome similarity and weight attributed')

parser.add_argument(
    '--full-graphml-path',
    type = str,
    help = 'Path(s) to the full Peptonizer graphml file for which you wish to cluster taxa (not containing communities).'
)
parser.add_argument(
    '--taxa-weights-dataframe-file',
    type = str,
    help = 'Path to file with weighted taxa computed in the taxa weighing step.'
)
parser.add_argument(
    '--similarity-threshold',
    type = float,
    help = 'Threshold for the peptidome similarity at which two taxa should belong to the same cluster.'
)
parser.add_argument(
    '--out',
    type = str,
    help= 'Path to clustered taxa output csv file.'
)

args = parser.parse_args()

clustered_taxa_df = cluster_taxa_based_on_similarity(
    nx.read_graphml(args.full_graphml_path),
    pd.read_csv(args.taxa_weights_dataframe_file),
    args.similarity_threshold
)

clustered_taxa_df.to_csv(args.out)
