from typing import Dict, List

from .ncbi_ranks import NCBI_RANKS
from .request_manager import RequestManager

class CommunicationException(Exception):
    pass

class UnipeptCommunicator:
    """
    Class responsible for retrieving data from Unipept.

    The default implementation in this class is used by the Python version of the Peptonizer, but can be overridden in
    case an alternative implementation is desired.

    :author: Pieter Verschaffelt
    """

    UNIPEPT_URL = "https://api.unipept.ugent.be"
    UNIPEPT_PEPT2FILTERED_ENDPOINT = "/api/v2/pept2taxa"
    UNIPEPT_TAXONOMY_ENDPOINT = "/api/v2/taxonomy"

    UNIPEPT_PEPTIDES_BATCH_SIZE = 2000
    TAXONOMY_ENDPOINT_BATCH_SIZE = 100

    # Static cache to store previously retrieved lineages
    lineage_cache = {}

    def get_taxa_for_peptides(self, peptides: List[str]) -> Dict[str, List[int]]:
        """
        Queries Unipept and returns all the taxa that are associated with the given list of peptides. For each peptide
        in the input, an entry in the output dictionary is created, which points to the taxon ids associated with this
        peptide.

        :param peptides: List of peptide sequences for which all associated taxa should be queried.

        :raises CommunicationException: If the Unipept API server responds with an error, or if something goes wrong
            with the network.

        :return: Dictionary mapping each peptide from the input list onto all of its associated taxa IDs.
        """
        url = UnipeptCommunicator.UNIPEPT_URL + UnipeptCommunicator.UNIPEPT_PEPT2FILTERED_ENDPOINT

        output = dict()

        # Split the peptides into batches of a predefined size
        for i in range(0, len(peptides), UnipeptCommunicator.UNIPEPT_PEPTIDES_BATCH_SIZE):
            batch = peptides[i:i+UnipeptCommunicator.UNIPEPT_PEPTIDES_BATCH_SIZE]

            # Prepare the request payload
            payload = {
                "input": batch,
                "compact": True,
                "tryptic": True
            }

            # Perform the HTTP POST request
            response = RequestManager.perform_post_request(url, payload)

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()
                for peptide_data in data:
                    original_taxa = peptide_data.get("taxa", [])
                    output[peptide_data["peptide"]] = original_taxa
            else:
                raise CommunicationException(f"Status code returned by Unipept API was {response.status_code}")

        return output

    def get_descendants_for_taxa(self, target_taxa: List[int], descendants_rank: str) -> List[int]:
        """
        Returns a list of all taxon IDs that are descendants of the given taxa in `target_taxa`.

        :param target_taxa: A list of taxon IDs for which all descendants at a specific NCBI rank (and lower) should be
            retrieved.
        :param descendants_rank: The maximum rank that each of the descendants should have in the NCBI taxonomy.
            All descendants that are defined at this rank or deeper are reported.

        :raises CommunicationException: If the Unipept API server responds with an error, or if something goes wrong
            with the network.

        :return: A list of taxon IDs that meet the given rank criteria.
        """
        url = UnipeptCommunicator.UNIPEPT_URL + UnipeptCommunicator.UNIPEPT_TAXONOMY_ENDPOINT
        all_descendants = set()  # Using a set to avoid duplicates

        # We need to get all children at the requested level, AND at lower levels. That's what we're using the ranks array
        # for.
        rank_idx = NCBI_RANKS.index(descendants_rank)
        descendants_ranks = NCBI_RANKS[rank_idx:]

        # Split the target taxa into batches of 15
        for i in range(0, len(target_taxa), UnipeptCommunicator.TAXONOMY_ENDPOINT_BATCH_SIZE):
            batch = target_taxa[i:i+UnipeptCommunicator.TAXONOMY_ENDPOINT_BATCH_SIZE]

            # Prepare the request payload
            payload = {
                "input": batch,
                "descendants": True,
                "descendants_ranks": descendants_ranks
            }

            # Perform the HTTP POST request
            response = RequestManager.perform_post_request(url, payload)

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()

                # Extract descendants from each item in the response
                for item in data:
                    all_descendants.update(item.get("descendants", []))
            else:
                raise CommunicationException(f"Status code returned by Unipept API was {response.status_code}")

        # Convert the set of descendants back to a list and return it
        return list(all_descendants)

    def get_lineages_for_taxa(self, target_taxa: List[int]) -> Dict[int, List[int | None]]:
        """
        Retrieve the lineage array for each of the taxon IDs in the provided target_taxa list. A lineage array is an
        array containing exactly 27 entries. Each position in the array corresponds to either the taxon ID of the parent
        node at that rank, or None if no parent is defined for this taxon at that rank.

        :param target_taxa: A list of taxon IDs for which the lineage arrays need to be retrieved.

        :raises CommunicationException: If the Unipept API server responds with an error, or if something goes wrong
            with the network.

        :return: A dictionary that contains an entry for every taxon ID from the input, mapped onto its lineage array.
        """
        url = UnipeptCommunicator.UNIPEPT_URL + UnipeptCommunicator.UNIPEPT_TAXONOMY_ENDPOINT

        # Remove duplicates from input and filter those already cached
        target_taxa = set(target_taxa)
        lineages = dict()

        # Prepare a list of taxa that are not yet in the cache
        taxa_to_request = [taxon for taxon in target_taxa if taxon not in self.lineage_cache]

        # Fetch lineages from the API for taxa not in the cache
        for i in range(0, len(taxa_to_request), UnipeptCommunicator.TAXONOMY_ENDPOINT_BATCH_SIZE):
            batch = taxa_to_request[i:i+UnipeptCommunicator.TAXONOMY_ENDPOINT_BATCH_SIZE]

            payload = {
                "input": batch,
                "extra": True
            }

            # Perform the HTTP POST request
            response = RequestManager.perform_post_request(url, payload)

            if response.status_code == 200:
                data = response.json()
                for item in data:
                    lineage = [item.get(rank + "_id") for rank in NCBI_RANKS]
                    taxon_id = item["taxon_id"]
                    # Cache the retrieved lineage
                    self.lineage_cache[taxon_id] = lineage
            else:
                raise CommunicationException(f"Status code returned by Unipept API was {response.status_code}")

        # Collect results from the cache for all requested taxa
        for taxon in target_taxa:
            lineages[taxon] = self.lineage_cache.get(taxon)

        return lineages

    def get_names_for_taxa(self, target_taxa: List[int]) -> Dict[int, str]:
        """
        Returns a mapping from taxon ID to taxon name for all taxa that have been provided to this function.

        :param target_taxa: A list of taxon IDs for which all corresponding taxon names should be retrieved.

        :raises CommunicationException: If the Unipept API server responds with an error, or if something goes wrong
            with the network.

        :return: A dictionary mapping taxon IDs to taxon names.
        """
        url = UnipeptCommunicator.UNIPEPT_URL + UnipeptCommunicator.UNIPEPT_TAXONOMY_ENDPOINT

        output = dict()

        # Split the target taxa into batches of 15
        for i in range(0, len(target_taxa), UnipeptCommunicator.TAXONOMY_ENDPOINT_BATCH_SIZE):
            batch = target_taxa[i:i+UnipeptCommunicator.TAXONOMY_ENDPOINT_BATCH_SIZE]

            # Prepare the request payload
            payload = {
                "input": batch
            }

            # Perform the HTTP POST request
            response = RequestManager.perform_post_request(url, payload)

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()

                # Extract descendants from each item in the response
                for item in data:
                    output[item.get("taxon_id")] = item.get("taxon_name")
            else:
                raise CommunicationException(f"Status code returned by Unipept API was {response.status_code}")

        return output
