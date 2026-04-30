import pandas as pd
import rbo

from scipy.stats import entropy
from typing import List, NamedTuple, Tuple


class ParameterSet(NamedTuple):
    """
    Represents a set of parameters that have been used for a Peptonizer analysis to tweak the behaviour of the belief
    propagation algorithm.
    """
    alpha: float
    beta: float
    prior: float


def compute_goodness(taxa_scores: dict, taxid_weights: pd.DataFrame):
    # Sort the taxa_scores dictionary by score in descending order
    sorted_tax_ids = sorted(taxa_scores.items(), key=lambda item: item[1], reverse=True)

    # Extract the sorted tax IDs and their corresponding scores
    sorted_ids = [tax_id for tax_id, score in sorted_tax_ids]
    sorted_scores = [score for tax_id, score in sorted_tax_ids]

    # Compute entropy of the posterior probability distribution
    computed_entropy = entropy(sorted_scores)

    # Compute the rank-based similarity between weight-sorted taxa and score-sorted ID results
    return rbo.RankingSimilarity(
        taxid_weights['HigherTaxa'].values,
        [int(tax_id) for tax_id in sorted_ids]
    ).rbo() * (1 / computed_entropy ** 2)


def find_best_parameters(results: List[Tuple[dict, ParameterSet]], taxid_weights: pd.DataFrame):
    """
    Given the dataframes that have been run through the Belief Propagation Algorithm before and the matching parameter
    sets, compute a goodness metric for each of these dataframes and returns the ParameterSet that resulted in the
    highest goodness value.

    :param results: A list of tuples each holding two things:
        1. A dict containing taxa and their associated scores after running the belief propagation algorithm
        2. The parameter values that where used during the belief propagation algorithm for this set of taxa
    :param taxid_weights: A dataframe containing taxa and their corresponding 'scaled weights', as computed by the]
    weight_taxa step.
    """
    params = []
    goodness_list = []

    for taxa_scores, param_set in results:
        goodness_list.append(compute_goodness(taxa_scores, taxid_weights))
        params.append(param_set)

    metrics_params = zip(goodness_list, params)
    sorted_metric_param_pairs = sorted(metrics_params, reverse = True)

    # Return the ParameterSet that's associated with the highest computed goodness metric.
    return sorted_metric_param_pairs[0][1]
