from io import StringIO

import peptonizer
import networkx as nx
import pandas as pd


graph_xml = globals().get('graph')
taxa_weights_csv = globals().get('taxa_weights_csv')
similarity_threshold = globals().get('similarity_threshold')

clustered_taxa_df = peptonizer.cluster_taxa_based_on_similarity(
    nx.read_graphml(StringIO(graph_xml)),
    pd.read_csv(StringIO(taxa_weights_csv)),
    similarity_threshold
)

print("Successfully generated clustered taxa!")

# Return a CSV version of the clustered taxa dataframe
clustered_taxa_df.to_csv()
