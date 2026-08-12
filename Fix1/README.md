## the SDRF builder loses the data that the agents found

**issues:** 7, 10, 11 and part of 13.

I tested this fix on 6 of the datasets.

## problem 

the llm agents read the paper and found the right answers but the code lost them before it
wrote the SDRF file.

for PXD005463 -> the agent found all of this with the exact sentence from the paper:

```json
"cleavage agent":     ["Trypsin", "Trypsin (Promega, sequencing grade) was added at a ratio of 1:30..."]
"alkylation reagent": ["iodoacetamide", "free sulfhydryl groups were carbamidomethylated using 30 mM iodoacetamide..."]
"reduction reagent":  ["DTT", "Cysteines were reduced with 10 mM DTT for 30 min at 56 degrees C"]
```

but the SDRF file said `cleavage agent details = not available` and had no fixed
modification.

## fix

### Part 1

file: `agents/integration_agent.py` in the repository `CompOmics/agentic-metadata`.

the function `enrich()` looked for value with an exact name match:

```python
llm_value = extracted.get(field)
```

the name come from `AGENT_FIELDS["TechnicalAgent"]` and these names use an underscore like:
`cleavage_agent` but the prompt in `core/prompts.py` asks the model for names with space like:`cleavage agent`

so every field name with two words become `null` and only `instrument` and `labeling` worked.

**fix:** small function make the name the same and it use lower case and changes spaces
and hyphens into underscores so code try exact name first then the clean name.

I did not use the function `resolve_field_name()` bc it look ok but it give the golden
benchmark names and not the agent names so it would change `labeling` into `label` and `tissue`
into `organ` and also it would make two different names into one name.

### Part 2

file: `src/python/sdrf_builder.py` in the repository `NCEMS/HAMLET`.

four functions only read the free text from PRIDE and they never look at the agent file:

- `_get_cleavage_agent()`
- `_get_reduction_reagent()`
- `_get_alkylation_reagent()`
- `_parse_protocol_mods()`

hamlet run PXD005463 in agentic only mode so results file has `pride_metadata: {}` and there is no text to read -> this is why Part1 alone does not change any SDRF file.

**fix:** these functions now read the agent value and the sentence from the paper and the function `_get_cleavage_agent()` also use the judge override -> override was already in the list `SAFE_SDRF_OVERRIDE_FIELDS` but the builder never reads it.


**Important:** I also added a new rule: if the alkylation reagent is iodoacetamide or chloroacetamide then write fixed Carbamidomethyl and I did not add NEM bc it has a different mass, also the code read the PRIDE text firstand it only read the agent data when the PRIDE text give no answer so this fix can only fill an empty field and it can never change value that is already there. 

### Part 3

file: `src/python/sdrf_builder.py`. 

the function `_parse_protocol_mods()` used this test:

```python
re.search(r"methylat", text, re.I)
```

the word `carbamidomethylated` contain the letters `methylat` so the test was true and the
code wrote a wrong `NT=Methyl;AC=UNIMOD:34;MT=Variable;TA=KR`.

my first idea was only `r"\bmethylat"` bc `\b` means "start of a word" so
`carbamidomethylated` does not match any more but I checked the 38 datasets that still match
and this was not enough, there was still two problems:

**problem 1 -> the word can be anywhere in the text and not in the search parameters.** in
PXD009281 the match is inside a paper title in the reference list:

```
Nucleosome-interacting proteins regulated by DNA and histone methylation. Cell 143, 470-484.
```

this is a citation and not a search parameter but the code still wrote a Methyl mod.

**problem 2 -> the residue `KR` was hardcoded and it is almost always wrong.** I read the
text of every dataset that match and they nearly all say lysine only:

```
PXD029361: variable ... methylation on K, demethylation on K and trimethylation on K
PXD036708: variable modifications of oxidation on methionine and methylation on lysine
PXD041775: methylation (K) ... were accepted as variable modifications
```

so the code wrote `TA=KR` but the truth is `TA=K`.

**fix:** now the code look for a residue near the word `methylat` (60 characters before and
after) and it take the residue from the text and it understand `lysine`, `Lys`, `(K)`, `[K]`,
`on K` and the same for arginine and if there is no residue near the word then it write nothing.

I also had to guard `Lys` bc `Lys-C` is a protease and not a residue.

result on all 2638 datasets that have PRIDE text:

| rule | datasets that get a Methyl mod |
|---|---|
| old `r"methylat"` | 906 |
| only `r"\bmethylat"` | 38 |
| `\b` plus residue from the text | 31 |

and the residue is not `KR` for everyone any more -> 21 datasets get `K`, 8 get `KR` and 2 get `R`.

I checked the 7 datasets that the residue rule drop and they are all correct to drop for
example: PXD040732 say "methylated N-termini" (this is not K or R) and PXD026687 say
"alkylation and methylation by DTT and IAA" -> this is sample prep and not a search mod

this bug is old and it is not new, in this fix I only saw it bc Part 2 make the code read
more text.

### Part 4

file: `src/python/sdrf_builder.py`.

the function `build_rows()` made one row for each raw file:

```python
for i, pf in enumerate(per_file):
```

and `_get_label()` gave back one text value from `_LABEL_MAP` so every multiplex experiment
became one single channel -> `tmt` became `TMT126` and `tmtpro` became `TMTpro126C`.

the builder find TMT and iTRAQ ok that part work but it had no model for channels so it
could not say that one raw file hold many samples. I checked all 306 saved SDRF files and in
all 306 the number of rows is the same as the number of data files.

for a TMTpro experiment with 16 channels this mean 15 samples out of every 16 are missing.

**fix:** I added channel lists for TMT with 6, 10, 11 and 16 channels and also TMTpro, iTRAQ
with 4 and 8 channels and SILAC heavy and light so a new map `_LABEL_CHANNELS` connect a label
to a list of channels and each channel is a list of label texts (SILAC need two texts, one
for R and one for K).

`build_rows()` now loop over files and then over channels and `source name` is different in
every row but `assay name` is the ms run so all channels of one file share it and
`comment[data file]` is also shared. the column `comment[label]` can now appear more than
once and this use the same method that modification parameters already use.

I did not invent the channel names or the SILAC codes -> I took them from the curated files
in `assets/gold_standard_sdrfs/`.

## results on 6 datasets

I chose 6 datasets to test different situations.

| dataset | fields found again | cleavage filled | mods added | mods removed | rows before | rows after |
|---|---|---|---|---|---|---|
| PXD005463 | 9 | yes | 1 | 0 | 3 | 3 |
| PXD001061 | 10 | yes | 1 | 0 | 30 | 30 |
| PXD000534 | 5 | yes | 1 | 0 | 16 | 256 |
| PXD001454 | 8 | no | 0 | 1 | 4 | 4 |
| PXD009281 | 8 | no | 0 | 1 | 2 | 2 |
| PXD041775 | 6 | no | 1 | 1 | 4 | 4 |
| **total** | **46** | **3** | **4** | **3** | | |

### what changed in each dataset

**PXD005463** no PRIDE text and cleavage agent went from `not available` to
`NT=Trypsin;AC=MS:1001251` -> same as the curated file and two new columns: alkylation reagent
(iodoacetamide) and reduction reagent (dithiothreitol) and fixed Carbamidomethyl was added ->
also same as the curated file.

**PXD001061** no PRIDE text and cleavage agent went from `not available` to
`NT=Lys-C;AC=MS:1001309` and two new columns: alkylation reagent (chloroacetamide) and
reduction reagent-> fixed Carbamidomethyl was added.

**PXD000534** no PRIDE text so cleavage agent went from `not available` to
`NT=Trypsin;AC=MS:1001251` and Oxidation was added. this dataset is TMTpro with 16 raw files
so Part 4 change it from 16 rows to 256 rows (16 files times 16 channels) and the alkylation
reagent is propionamide so the code correctly did NOT write Carbamidomethyl.

**PXD001454** the wrong Methyl mod was removed (the text say `carbamidomethylated`) and a
reduction reagent column appeared and the cleavage agent stayed as trypsin.

**PXD009281** the wrong Methyl mod was removed and this one is the citation in the reference
list, so only the new residue rule can catch it.

**PXD041775** the Methyl mod stayed but the residue was corrected from `TA=KR` to `TA=K` bc
the text say `methylation (K)`.

### the carbamidomethyl rule works ok

| dataset | alkylation reagent | carbamidomethyl written |
|---|---|---|
| PXD005463 | iodoacetamide | yes |
| PXD001061 | chloroacetamide | yes |
| PXD001454 | unknown | yes from PRIDE text |
| PXD000534 | propionamide | no |

PXD000534 is important bc propionamide is a different chemical with a different mass and the
code correctly did not write carbamidomethyl.

## one problem I found and fixed

my first version of Part 2 had a bug and I want to explain it here bc it shows why the final version
read the PRIDE text first.

in the first version the code joined the PRIDE text and the agent text together and then
searched this long text but `_get_cleavage_agent()` return the **first** enzyme it finds and
the list has this order: chymotrypsin, Lys-C, Asp-N, Glu-C, trypsin -> so Lys-C come before
trypsin.

on PXD001454 this changed the answer:

- the PRIDE text says `enzyme, trypsin`
- the agent said `Lys-C` and the evidence was "digested with endoproteinase Lys-C followed by
  modified trypsin digestion"
- so the old SDRF said Trypsin and the new SDRF said Lys-C

the sample used both enzymes so the perfect answer is both but this fix should not change a
value that is already there, so I changed the code -> now it read the PRIDE text first and it
only read the agent text when the PRIDE text give no answer.

I tested this on all 6 datasets:

**0 values were changed and every change is a new value in an empty field or a wrong Methyl mod
that was removed or a residue that was corrected.**

## SILAC is ready but it need one more fix

PXD005463 is SILAC but the row number did not change -> this is correct bc runAssessor only
look for isobaric reporter ions (TMT and iTRAQ) and SILAC has no reporter ions, so
runAssessor say `labeling: none` and the builder make one channel -> this is issue 9 and it is
a different fix.

Part 4 already build the SILAC rows so issue 9 only need a change in the detection part.

the folder `after_silac_demo/` show this & I used the same input files and I only changed
`runAssessor.search_criteria.labeling` to `SILAC` by hand and nothing else:

| | rows | label columns |
|---|---|---|
| today | 3 | 1 |
| with Part 4 and the label set by hand | 6 | 2 |
| curated file from bigbio | 6 | 2 |

```
PXD005463-Sample-1  qExPlus02_01602.raw  AC=PRIDE:0000615;NT=SILAC heavy R:13C(6)15N(4)  ||  AC=PRIDE:0000617;NT=SILAC heavy K:13C(6)15N(2)
PXD005463-Sample-2  qExPlus02_01602.raw  AC=PRIDE:0000611;NT=SILAC light R:12C(6)14N(4)  ||  AC=PRIDE:0000613;NT=SILAC light K:12C(6)14N(2)
```

the label part is the same as the curated file, row by row but remember this folder is
a demo and not a real pipeline result bc I edited an input file by hand.

## what is in this folder

- `README.md` 
- `before/` has 6 SDRF files made with the old code
- `after/` has 6 SDRF files made with the new code
- `after_silac_demo/` has 1 SDRF file, it show Part 4 with the label set by hand
- `evidence/before/` and `evidence/after/` have the enriched TechnicalAgent JSON for each
  dataset -> these show Part 1
- `_tools/` has the patches and the scripts

in `_tools/`:

- `Fix1_agentic-metadata.patch` is Part 1
- `Fix1_HAMLET.patch` is Part 2, Part 3 and Part 4
- `build_sdrf.py` builds the SDRF file for one dataset
- `regenerate.sh` builds all the before and after files again
- `store_scan.py` counts how many datasets have the Methyl problem and the channel problem
- `store_scan_output.txt` is the result of that script

## better to be aware of

the four parts belong to one fix but the files live in two repositories:

- Part 1 is in `CompOmics/agentic-metadata` -> hamlet uses it as a submodule at
  `src/agentic-metadata`
- Part 2, Part 3 and Part 4 are in `NCEMS/HAMLET`

so Part 1 need to go in first and after that hamlet need a new submodule commit, if someone
only test the hamlet patch then the cleavage agent will not change for datasets without PRIDE
text.

## how to use the patches

the code is clean now and the fix is only in the patch files, run this from the root folder of the HAMLET repository, for example I did this:

```bash
git -C src/agentic-metadata apply "/Users/fateme/Desktop/Changes/Fix1/_tools/Fix1_agentic-metadata.patch"
git apply /Users/fateme/Desktop/Changes/Fix1/_tools/Fix1_HAMLET.patch
```

## how to make the files again

run this from the root folder of the HAMLET repository:

```bash
bash /Users/fateme/Desktop/Changes/Fix1/_tools/regenerate.sh
HAMLET_REPO=$PWD python3 /Users/fateme/Desktop/Changes/Fix1/_tools/store_scan.py
```

the script apply the patches, build the files and then make the code clean again.

## how many datasets does this help

I looked at all the saved files and the full result is in `_tools/store_scan_output.txt`.

the Methyl problem:

| | count |
|---|---|
| datasets with PRIDE text | 2638 |
| get a Methyl mod with the old rule | 906 |
| get a Methyl mod with the new rule | 31 |
| saved SDRF files that carry a wrong Methyl today | 105 |

the channel problem:

| | count |
|---|---|
| saved SDRF files where rows are the same as data files | 306 out of 306 |
| saved SDRF files where the label has more than one channel | 45 |
| rows in those 45 files today | 95 |
| rows in those 45 files after Part 4 | 1210 |

so those 45 datasets show 95 rows today but they should show 1210 rows.

