import pandas as pd
import peptonizer

from io import StringIO

clusteredTaxaWeightsCsv = globals().get('clustered_taxa_weights_csv')
peptonizer_results = globals().get('peptonizer_results')

peptonizer.compute_goodness(peptonizer_results, pd.read_csv(StringIO(clusteredTaxaWeightsCsv)))
