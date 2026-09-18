# HAMLET SDRF Gold-Cohort Candidate Review

Date: 2026-09-17

Status: Approved score-ranked 30-PXD HAMLET v2.1.0 gold cohort on 2026-09-17. The fixture manifest retains the caveats recorded below; approval does not represent the listed issues as defect-free.

## 1. Selection Data

This review surveyed the current stored HAMLET v2.1.0 SDRFs. Each candidate below has all of the following:

1. `store/hamlet_sdrfs/PXD######.sdrf.tsv` declares `HAMLET-agentic v2.1.0`.
2. A final post-judge CSV, review CSV, JSON report, and confidence sidecar exist under `store/agentic_results_files/PXD######/`.
3. A matching aggregate JSON exists.
4. That aggregate contains nonempty RunAssessor output, organism-identification results, and search/modification results.

The aggregate records are historical `pipeline_version: "1.0"` documents and do not contain `run_mode`; they were accepted based on actual stage evidence, not their legacy labels.

| Store measure | Count |
| --- | ---: |
| Stored SDRFs inspected | 490 |
| SDRFs declaring `HAMLET-agentic v2.1.0` | 371 |
| v2.1.0 SDRFs with complete final judge metrics | 308 |
| Fully evidenced candidates | 287 |
| Fully evidenced candidates without a critical-field hallucination or type mismatch | 25 |

## 2. Approved Score-Ranked Cohort

The following 30 are the approved highest-ranked fully evidenced candidates using final strict `judge_accuracy` descending, then total hallucinations and type mismatches ascending. `RA files` and `Organism records` are direct aggregate evidence counts. The listed critical-field concerns must be preserved in fixture metadata and used to interpret later QC results.

| Rank | PXD | Accuracy | Correct / total | Halluc. | Mismatch | Wrong | Incomplete | SDRF rows / columns | RA files | Organism records | Critical-field concern |
| ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | PXD003544 | 0.9583 | 23 / 24 | 0 | 0 | 0 | 1 | 8 / 35 | 4 | 4 | None found |
| 2 | PXD034594 | 0.9583 | 23 / 24 | 1 | 0 | 0 | 0 | 3 / 31 | 1 | 1 | None found |
| 3 | PXD005048 | 0.9565 | 22 / 23 | 0 | 0 | 1 | 0 | 4 / 32 | 1 | 1 | None found |
| 4 | PXD032144 | 0.9474 | 18 / 19 | 1 | 0 | 0 | 0 | 3 / 36 | 3 | 3 | None found |
| 5 | PXD044188 | 0.9091 | 20 / 22 | 2 | 0 | 0 | 0 | 3 / 31 | 1 | 1 | Acquisition-method hallucination |
| 6 | PXD033196 | 0.9048 | 19 / 21 | 1 | 0 | 0 | 1 | 2 / 27 | 2 | 2 | None found |
| 7 | PXD073162 | 0.9048 | 19 / 21 | 1 | 0 | 1 | 0 | 4 / 31 | 4 | 4 | Modification hallucination |
| 8 | PXD024054 | 0.9000 | 18 / 20 | 0 | 0 | 0 | 2 | 2 / 36 | 2 | 2 | None found |
| 9 | PXD072078 | 0.9000 | 18 / 20 | 1 | 0 | 1 | 0 | 1 / 29 | 1 | 1 | Modification hallucination |
| 10 | PXD001454 | 0.8947 | 17 / 19 | 1 | 0 | 0 | 1 | 4 / 30 | 4 | 4 | Modification hallucination |
| 11 | PXD030978 | 0.8750 | 14 / 16 | 0 | 1 | 1 | 0 | 2 / 37 | 1 | 1 | None found |
| 12 | PXD015445 | 0.8696 | 20 / 23 | 3 | 0 | 0 | 0 | 4 / 35 | 4 | 4 | Modification hallucination |
| 13 | PXD001805 | 0.8636 | 19 / 22 | 1 | 1 | 1 | 0 | 1 / 36 | 1 | 1 | Modification type mismatch |
| 14 | PXD038818 | 0.8636 | 19 / 22 | 2 | 0 | 1 | 0 | 3 / 33 | 3 | 3 | Modification hallucination and type mismatch |
| 15 | PXD036708 | 0.8636 | 19 / 22 | 3 | 0 | 0 | 0 | 3 / 31 | 3 | 3 | Modification hallucination |
| 16 | PXD008215 | 0.8571 | 12 / 14 | 1 | 0 | 0 | 1 | 4 / 29 | 3 | 3 | Modification hallucination |
| 17 | PXD014472 | 0.8571 | 18 / 21 | 3 | 0 | 0 | 0 | 1 / 28 | 1 | 1 | Acquisition-method and modification hallucinations |
| 18 | PXD032738 | 0.8571 | 18 / 21 | 3 | 0 | 0 | 0 | 3 / 34 | 1 | 1 | Modification hallucination and type mismatch |
| 19 | PXD020418 | 0.8500 | 17 / 20 | 0 | 0 | 1 | 2 | 2 / 32 | 2 | 2 | None found |
| 20 | PXD015800 | 0.8500 | 17 / 20 | 1 | 1 | 0 | 1 | 5 / 30 | 4 | 4 | None found |
| 21 | PXD025590 | 0.8500 | 17 / 20 | 2 | 1 | 0 | 0 | 4 / 28 | 3 | 3 | Modification hallucination and type mismatch |
| 22 | PXD004802 | 0.8500 | 17 / 20 | 3 | 0 | 0 | 0 | 3 / 31 | 3 | 3 | Modification hallucination |
| 23 | PXD009266 | 0.8500 | 17 / 20 | 3 | 0 | 0 | 0 | 3 / 32 | 3 | 3 | Modification hallucination |
| 24 | PXD030847 | 0.8500 | 17 / 20 | 3 | 0 | 0 | 0 | 4 / 31 | 4 | 4 | Modification hallucination |
| 25 | PXD011237 | 0.8421 | 16 / 19 | 1 | 0 | 1 | 1 | 2 / 31 | 2 | 2 | None found |
| 26 | PXD037474 | 0.8421 | 16 / 19 | 1 | 0 | 1 | 1 | 4 / 33 | 2 | 2 | None found |
| 27 | PXD004997 | 0.8421 | 16 / 19 | 3 | 0 | 0 | 0 | 4 / 31 | 3 | 3 | Modification hallucination |
| 28 | PXD037990 | 0.8421 | 16 / 19 | 3 | 0 | 0 | 0 | 3 / 30 | 3 | 3 | Modification hallucination |
| 29 | PXD059345 | 0.8333 | 15 / 18 | 2 | 0 | 1 | 0 | 3 / 31 | 1 | 1 | Modification hallucination |
| 30 | PXD018851 | 0.8333 | 20 / 24 | 3 | 1 | 0 | 0 | 3 / 33 | 1 | 1 | Modification hallucination and type mismatch |

## 3. Strict-Filter Result

The plan's proposed strict rule excludes an SDRF if the final annotation review flags a hallucination or type mismatch for organism/species, instrument, acquisition method, modification/PTM, precursor tolerance, fragment tolerance, fragmentation method, or mass analyzer.

Only the following 25 fully evidenced candidates pass that rule. They are not an adequate 30-PXD baseline by themselves, because the five lowest scores are substantially below the preferred high-quality threshold.

```text
PXD003544  PXD034594  PXD005048  PXD032144  PXD033196
PXD024054  PXD030978  PXD020418  PXD015800  PXD011237
PXD037474  PXD029013  PXD065770  PXD012723  PXD053088
PXD019412  PXD044860  PXD025776  PXD048763  PXD056030
PXD025803  PXD065314  PXD036779  PXD057905  PXD027729
```

Their final strict judge accuracies range from `0.9583` to `0.5294`.

## 4. Accepted Cohort Record

The score-ranked 30 above is the accepted initial v2.1.0 HAMLET gold cohort. The strict-filter 25 remains a diagnostic subset only; it does not replace the approved cohort. Fixture generation copies the final SDRF, confidence sidecar, and final post-judge artifacts for every approved PXD, recording each listed caveat as baseline metadata so a known issue is never silently treated as a later regression or as evidence of defect-free output.