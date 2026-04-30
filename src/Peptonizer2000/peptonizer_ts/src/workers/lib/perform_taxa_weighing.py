import peptonizer

# The PSM input should be provided to the parser as a list of strings
pep_scores = globals().get('peptides_scores')
pep_counts = globals().get('peptides_counts')
rank = globals().get('rank')
taxa_in_graph = globals().get('taxa_in_graph')
peptides_taxa = globals().get('peptides_taxa')

# Infer the taxa weights for these peptide sequences
sequence_scores_df, taxa_weights_df = peptonizer.perform_taxa_weighing(
    peptides_taxa,
    pep_scores,
    pep_counts,
    taxa_in_graph,
    peptonizer.UnipeptCommunicator(),
    rank
)

# Return a CSV-representation of the taxa_weights dataframe
output = [sequence_scores_df.to_csv(), taxa_weights_df.to_csv()]
output
