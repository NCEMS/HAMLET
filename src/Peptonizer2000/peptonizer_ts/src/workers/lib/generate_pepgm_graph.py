from io import StringIO

import peptonizer
import pandas as pd

# The PSM input should be provided to the parser as a list of strings
taxa_weights_csv = globals().get('taxa_weights_csv')

# Finally use the computed weights to generate the graph
pepgm_graph = peptonizer.generate_pepgm_graph(pd.read_csv(StringIO(taxa_weights_csv), dtype={"HigherTaxa": "Int64"}))

# Return an XML representation of the generated peptonizer graph
pepgm_graph.to_graph_ml()
