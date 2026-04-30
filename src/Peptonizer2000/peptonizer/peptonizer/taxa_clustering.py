import networkx as nx
import pandas as pd


def get_peptides_per_taxon(graph_in: nx.Graph):
    peptidome_dict = {}
    for node in graph_in.nodes(data = True):
        if node[1]['category'] == 'taxon' and node[0]:
            neighbors = graph_in.neighbors(node[0])
            peptidome_dict.update({node[0]: [n[:-4] for n in neighbors]})
    return peptidome_dict


def compute_detected_peptidome_similarity(peptidome_dict):
    sim_matrix_max = []
    taxa1 = []
    taxa2 = []
    for taxon1 in peptidome_dict.keys():
        taxa1.append(taxon1)
        sim_matrix_max_row = []
        for taxon2 in peptidome_dict.keys():
            taxa2.append(taxon2)
            peptides1 = set(peptidome_dict[taxon1])
            peptides2 = set(peptidome_dict[taxon2])
            shared = len(peptides1.intersection(peptides2))
            try:
                sim = shared / (len(peptides2))
            except:
                sim = 0

            sim_matrix_max_row.append(sim)

        sim_matrix_max.append(sim_matrix_max_row)

    similarity_frame = pd.DataFrame(sim_matrix_max, columns = taxa1, index = taxa1)
    return similarity_frame


def cluster_taxa_based_on_similarity(
        pepgm_graph: nx.Graph,
        taxid_weights: pd.DataFrame,
        similarity_threshold: float
):
    peptidome_dict = get_peptides_per_taxon(pepgm_graph)
    similarities = compute_detected_peptidome_similarity(peptidome_dict)

    taxid_weights = taxid_weights.loc[taxid_weights.HigherTaxa.isin([int(x) for x in similarities.index.tolist()])]

    list_of_weight_sorted_taxa = taxid_weights.HigherTaxa.tolist()
    taxa_cluster_list = []

    cluster_heads = [taxid_weights.HigherTaxa[0]]

    while list_of_weight_sorted_taxa:
        taxon1 = list_of_weight_sorted_taxa[0]
        cluster_list = []
        cluster_heads.append(list_of_weight_sorted_taxa[0])

        for taxon2 in taxid_weights.HigherTaxa:
            if similarities[str(int(taxon2))][str(int(taxon1))] > similarity_threshold:
                cluster_list.append(taxon2)
                if taxon2 in list_of_weight_sorted_taxa:
                    list_of_weight_sorted_taxa.remove(taxon2)

        taxa_cluster_list.append(cluster_list)


    clustered_weight_sorted_taxa = taxid_weights.loc[taxid_weights.HigherTaxa.isin(cluster_heads)]
    clustered_weight_sorted_taxa2 = taxid_weights.loc[taxid_weights.HigherTaxa.isin([clustered_taxa[1:] for clustered_taxa in taxa_cluster_list])]
    clustered_weight_sorted_taxa = pd.concat([clustered_weight_sorted_taxa, clustered_weight_sorted_taxa2])
    clustered_weight_sorted_taxa['Clustermembers'] = taxa_cluster_list

    return clustered_weight_sorted_taxa
