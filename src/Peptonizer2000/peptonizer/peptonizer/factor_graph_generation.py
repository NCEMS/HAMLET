from typing import List, Any

import numpy as np
import networkx as nx
import pandas as pd

from . import array_utils
from collections import namedtuple


class TaxonGraph(nx.Graph):
    """
    Class with functions to construct a peptide-taxon graph using Entrez/NCBI mapping.
    """
    def __init__(self):
        super().__init__()
        self.taxon_id_list = []

    def create_from_taxa_weights(self, taxa_weights):
        # drop rows that have an entry in HigherTaxa that appears only once
        counts = taxa_weights["HigherTaxa"].value_counts()
        taxa_weights = taxa_weights[
            taxa_weights["HigherTaxa"].isin(counts[counts > 1].index)
        ]
        new_graph = nx.from_pandas_edgelist(taxa_weights, "sequence", "HigherTaxa")
        peptide_attributes = taxa_weights.apply(
            lambda row: (
                row["sequence"],
                {
                    "InitialBelief_0": 1 - float(row["score"]),
                    "InitialBelief_1": float(row["score"]),
                    "category": "peptide",
                },
            ),
            axis=1,
        )
        taxa_attributes = taxa_weights.apply(
            lambda row: (row["HigherTaxa"], {"category": "taxon"}), axis=1
        )
        intermediate_graph = nx.Graph()
        intermediate_graph.add_edges_from(new_graph.edges)
        intermediate_graph.add_nodes_from(peptide_attributes)
        intermediate_graph.add_nodes_from(taxa_attributes)

        self.add_edges_from(intermediate_graph.edges)
        self.add_nodes_from(peptide_attributes)
        self.add_nodes_from(taxa_attributes)


class Factor:
    # represents noisy OR cpds, has dimension n(parensports)xn(peptide states(=2))
    def __init__(self, cpd_array, variable_array):
        Factor = namedtuple("Factor", ["array", "arrayLabels"])
        self.factor = Factor(cpd_array, variable_array)


# the variable and factor types might be unecessary as i do not need a lot of flexibility in the input


class FactorGraph(nx.Graph):
    def __init__(self):
        super().__init__()

    def construct_from_existing_graph(self, graph_data: nx.Graph):
        node_list = list(graph_data.nodes(data=True))
        self.add_nodes_from(node_list)
        for node in node_list:
            # create noisy OR cpd per peptide
            if node[1]["category"] == "peptide":
                degree = graph_data.degree(node[0])
                neighbors = list(graph_data.neighbors(node[0]))
                self.add_node(node[0] + " CPD", category="factor", ParentNumber=degree)
                self.add_edges_from([(node[0] + " CPD", x) for x in neighbors])
                self.add_edge(node[0] + " CPD", node[0])


# separate the connected components in the subgraph
def separate_subgraphs(graph_in, nodes_to_keep):
    """
    separations of subgraphs (create news graphs for each subgraph)

    """
    new_graph = CTFactorGraph(nx.Graph())

    # add nodes to keep
    new_graph.add_nodes_from((n, graph_in.nodes[n]) for n in nodes_to_keep)
    # add edges if they are present in original graph
    new_graph.add_edges_from(
        (n, nbr, d)
        for n, nbrs in graph_in.adj.items()
        if n in nodes_to_keep
        for nbr, d in nbrs.items()
        if nbr in nodes_to_keep
    )

    return new_graph  # ListOfFactorGraphs


class CTFactorGraph(FactorGraph):
    """'
    This class is a networkx graph representing the full graphical model with all variables, CTrees, and Noisy-OR factors
    """

    def __init__(self, graph_in, graph_type="Taxons"):
        """
        takes either a graph or a path to a graphML file as input

        """
        super().__init__()

        graph_types = ["Proteins", "Taxons"]
        if graph_type not in graph_types:
            raise ValueError("Invalid Graphtype. Expected one of: %s" % graph_types)

        if graph_type == "Taxons":
            self.category = "taxon"
        elif graph_type == "Protein":
            self.category = "protein"

        if isinstance(graph_in, str):
            graph_in = nx.parse_graphml(graph_in)

        # need these to create a new instance of a CT fractorgraph and not overwrite the previous graph
        self.add_edges_from(graph_in.edges(data=True))
        self.add_nodes_from(graph_in.nodes(data=True))

    def add_ct_nodes(self):
        """
        When creating the CTGraph and not just reading from a previously saved graph format, use this command to add the CT nodes
        """
        # create the convolution tree nodes and connect them in the graph
        list_of_edge_add_list = []
        list_of_edge_remove_list = []
        list_of_prot_lists = []
        list_of_cts = []
        list_of_factors = []

        for node in self.nodes(data=True):
            # go through all factors with degree>2 and get their protein lists, then generate their conv. trees
            if node[1]["category"] == "factor" and self.degree[node[0]] > 2:
                prot_list = []

                for neighbour in self.neighbors(node[0]):
                    neighbour_node = self.nodes[neighbour]
                    if neighbour_node["category"] == self.category:
                        prot_list.append(neighbour)

                list_of_cts.append([1])
                list_of_factors.append(node[0])
                list_of_prot_lists.append(prot_list)
                list_of_edge_add_list.append(
                    [("CTree " + " ".join(str(prot_list)), x) for x in prot_list]
                )
                list_of_edge_remove_list.append([(node[0], x) for x in prot_list])

        # Fill all info into graph structure, should probably do this inside the loop before, so that i can initialize
        # the messages
        for i in range(len(list_of_cts)):
            self.add_node(
                "CTree " + " ".join(str(list_of_prot_lists[i])),
                category="convolution_tree",
                NumberOfParents=len(list_of_prot_lists[i]),
            )
            self.add_edge(
                "CTree " + " ".join(str(list_of_prot_lists[i])),
                list_of_factors[i],
                MessageLength=len(list_of_prot_lists[i]) + 1,
            )
            self.add_edges_from(list_of_edge_add_list[i])
            self.remove_edges_from(list_of_edge_remove_list[i])

    def save_to_graph_ml(self, filename):
        nx.write_graphml(self, filename)

    def to_graph_ml(self):
        return '\n'.join(nx.generate_graphml(self))

    def compute_network_attributes(self):
        """
        Computes nodes attributes using builtin networkx functions
        Returns degree centrality, closeness centrality, betweenness centrality and eigen centrality
        """
        degree_centrality = dict(
            sorted(nx.degree_centrality(self).items(), key=lambda item: item[1])
        )
        closeness_centrality = dict(
            sorted(nx.closeness_centrality(self).items(), key=lambda item: item[1])
        )
        betweenness_centrality = dict(
            sorted(nx.betweenness_centrality(self).items(), key=lambda item: item[1])
        )
        eigen_centrality = dict(
            nx.eigenvector_centrality(self).items(), key=lambda item: item[1]
        )

        return (
            degree_centrality,
            closeness_centrality,
            betweenness_centrality,
            eigen_centrality,
        )

    def fill_in_factors(self, alpha, beta, regularized):
        """fills in the noisy or Factors according to detection and error probabilities given"""

        for node in self.nodes(data=True):
            # create noisy OR cpd per peptide
            if node[1]["category"] == "factor":
                # add noisyOR factors
                degree = node[1]["ParentNumber"]
                # pre-define the CPD array and fill it with the noisyOR values
                cpd_array = np.full([2, degree + 1], 1 - alpha)
                cpd_array_regularized = np.full([2, degree + 1], 1 - alpha)
                exponent_array = np.arange(0, degree + 1)
                divide_array = np.concatenate(
                    (np.asarray([1]), np.arange(1, degree + 1))
                )
                # regularize cpd priors to penalize higher number of parents
                # log domain to avoid underflow
                cpd_array[0, :] = np.power(cpd_array[0, :], exponent_array) * (1 - beta)
                cpd_array_regularized[0, :] = np.divide(
                    np.power(cpd_array[0, :], exponent_array) * (1 - beta), divide_array
                )
                # check0 = cpd_array_regularized[0,:]
                # check1 = cpd_array[0,:]
                cpd_array[1, :] = np.add(-cpd_array[0, :], 1)
                cpd_array_regularized[1, :] = np.add(-cpd_array_regularized[0, :], 1)
                cpd_array = np.transpose(array_utils.normalize(cpd_array))
                cpd_array_regularized = array_utils.avoid_underflow(
                    np.transpose(array_utils.normalize(cpd_array_regularized))
                )
                if regularized:
                    factor_to_add = Factor(
                        cpd_array_regularized,
                        ["placeholder", [node[0] + "0", node[0] + "1"]],
                    )
                else:
                    factor_to_add = Factor(
                        cpd_array, ["placeholder", [node[0] + "0", node[0] + "1"]]
                    )

                # add factor & its edges to network as an extra node
                nx.set_node_attributes(self, {node[0]: factor_to_add}, "InitialBelief")

    def fill_in_priors(self, prior):
        """fills in the taxon priors according to the given prior"""

        for node in self.nodes(data=True):
            # create noisy OR cpd per peptide
            if node[1]["category"] == "taxon":
                nx.set_node_attributes(
                    self,
                    {node[0]: {"InitialBelief_0": 1 - prior, "InitialBelief_1": prior}},
                )

def generate_pepgm_graph(
    taxa_weights_data_frame: pd.DataFrame
) -> CTFactorGraph:
    taxon_graph = TaxonGraph()
    taxon_graph.create_from_taxa_weights(taxa_weights_data_frame)
    factor_graph = FactorGraph()
    factor_graph.construct_from_existing_graph(taxon_graph)
    return CTFactorGraph(factor_graph, "Taxons")
