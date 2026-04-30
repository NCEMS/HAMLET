import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from .unipept_communicator import UnipeptCommunicator


def plot_peptonizer_results(input_file: str, output_file: str, number_of_taxa: int = 25):
    """
    Read the results of a Peptonizer run from a CSV-file (denoted by the input_file argument) and write bar charts
    representing these results to a PNG-file.
    """
    assert input_file.lower().endswith(".csv"), "Input file should be a CSV."
    assert output_file.lower().endswith(".png"), "Output file should be a PNG."

    # read csv using pandas
    ids = pd.read_csv(input_file, names=["ID", "score", "type"])
    tax_ids = ids.loc[ids["type"] == "taxon"].dropna().copy()

    # Avoid Arrow-backed string dtype assignment errors by replacing the column.
    tax_ids["score"] = pd.to_numeric(tax_ids["score"], errors="coerce", downcast="float")
    tax_ids = tax_ids.dropna(subset=["score"])
    tax_ids = tax_ids.sort_values("score")
    taxa_check = tax_ids.ID.tolist()

    # translate taxids to scientific names
    unipept_communicator = UnipeptCommunicator()

    taxa_name_dict = unipept_communicator.get_names_for_taxa([int(x) for x in tax_ids["ID"]])
    taxa_names = [taxa_name_dict[int(tax)] for tax in taxa_check]
    scores = tax_ids["score"]

    # make the barplot
    fig, ax = plt.subplots()
    fig.set_size_inches(30, 15)
    bars = ax.barh(
        range(len(taxa_names[-number_of_taxa:])),
        scores[-number_of_taxa:],
        color="#283593",
    )

    ax.set_yticks(range(len(taxa_names[-number_of_taxa:])))
    ax.set_yticklabels(taxa_names[-number_of_taxa:], fontsize=24, color="#283593", fontweight="bold")
    ax.tick_params(axis='y', which='major', pad=15)
    plt.xlim((0, 1))
    plt.xlabel("Probability score", fontsize=35, fontweight="bold")
    ax.xaxis.set_ticks(np.arange(0, 1.2, 0.2))
    ax.xaxis.set_ticklabels([0, 0.2, 0.4, 0.6, 0.8, 1.0], fontsize=35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.bar_label(bars, fmt='{:,.3f}', fontsize=24, fontweight='bold', color='black', padding=20)

    fig.tight_layout()

    plt.savefig(output_file)
    plt.close()
