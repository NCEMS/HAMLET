class PeptonizerInputParser {
    /**
     * Parses the given TSV string and returns two maps:
     * - peptidesScores: Maps peptide sequences to their maximum score.
     * - peptidesCounts: Maps peptide sequences to their occurrence count.
     * @param tsvContent The content of the TSV file as a string.
     * @returns An object containing peptidesScores and peptidesCounts maps.
     */
    static parse(tsvContent: string): [
        peptidesScores: Map<string, number>,
        peptidesCounts: Map<string, number>
    ] {
        const peptidesScores = new Map<string, number>();
        const peptidesCounts = new Map<string, number>();

        const lines = tsvContent.trim().split('\n');

        // Skip the header from the file
        for (const line of lines.splice(1)) {
            const [peptide, scoreString] = line.split('\t');
            const score = parseFloat(scoreString);

            if (!peptide || isNaN(score)) {
                throw new Error(`Invalid line in TSV file: ${line}`);
            }

            // Update peptide counts
            const currentCount = peptidesCounts.get(peptide) || 0;
            peptidesCounts.set(peptide, currentCount + 1);

            // Update peptide scores (store the maximum score)
            const currentMaxScore = peptidesScores.get(peptide) || Number.NEGATIVE_INFINITY;
            peptidesScores.set(peptide, Math.max(currentMaxScore, score));
        }

        return [peptidesScores, peptidesCounts];
    }
}

export { PeptonizerInputParser };
