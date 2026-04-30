import matplotlib
import argparse

from peptonizer.peptonizer import plot_peptonizer_results

"""
Script that takes PepGM .csv output, translates taxIDS to scientific names, and barplots the *number of results* highest
scoring taxa.
"""

matplotlib.use("Agg")

parser = argparse.ArgumentParser(description="Generate BarPlot of PepGM results.")

parser.add_argument(
    "--results-file", type=str, help="Path(s) to your PepGM results CSV."
)
parser.add_argument(
    "--number-of-results",
    type=int,
    default=12,
    help="How many taxa you want to show up on the results plot.",
)
parser.add_argument(
    "--out",
    type=str,
    help="Path(s) to where the generated BarPlot PNG's should be stored.",
)

args = parser.parse_args()
plot_peptonizer_results(args.results_file, args.results_file.replace(".csv", ".png"), args.number_of_results)
