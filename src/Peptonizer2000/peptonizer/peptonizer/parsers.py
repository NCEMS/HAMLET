from typing import Dict, Tuple

def parse_peptide_tsv(tsv_content: str) -> Tuple[Dict[str, float], Dict[str, int]]:
    """
    Parses a TSV string with columns 'peptide' and 'score', where peptides can occur multiple times.

    :param tsv_content: str, content of a TSV file with 'peptide' and 'score' columns.
    :return: Tuple containing two dictionaries:
        - pep_score: Maps peptide sequence to score (float).
        - pep_psm_counts: Maps peptide sequence to the count of occurrences.
    """
    pep_score: Dict[str, float] = {}
    pep_psm_counts: Dict[str, int] = {}

    # Process each line in the TSV content, skipping the header
    for line in tsv_content.splitlines()[1:]:
        if line.strip() == "":  # Skip empty lines
            continue

        peptide, score = line.split("\t")
        score = float(score)

        # Update pep_score dictionary
        pep_score[peptide] = score  # Assumes the latest score in the file should be used

        # Update pep_psm_counts dictionary
        if peptide in pep_psm_counts:
            pep_psm_counts[peptide] += 1
        else:
            pep_psm_counts[peptide] = 1

    return pep_score, pep_psm_counts
