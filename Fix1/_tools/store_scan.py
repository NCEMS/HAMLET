import csv, glob, json, os, re, sys
from collections import Counter

REPO = os.environ.get("HAMLET_REPO", os.getcwd())
SDRFS = sorted(glob.glob(os.path.join(REPO, "store/hamlet_sdrfs/*.sdrf.tsv")))
AGG = os.path.join(REPO, "store/aggregated_results_files/%s_aggregated_results.json")
OLD, NEW = re.compile(r"methylat", re.I), re.compile(r"\bmethylat", re.I)

CHANNEL_COUNT = {
    "tmt": 6, "tmt2": 2, "tmt6": 6, "tmt6plex": 6,
    "tmt10": 10, "tmt10plex": 10, "tmt11": 11, "tmt11plex": 11,
    "tmt16": 16, "tmt16plex": 16, "tmtpro": 16,
    "itraq": 4, "itraq4": 4, "itraq4plex": 4, "itraq8": 8, "itraq8plex": 8,
    "silac": 2, "silac2": 2,
}

def protocol_text(pxd):
    p = AGG % pxd
    if not os.path.exists(p):
        return None
    proj = (json.load(open(p)).get("pride_metadata") or {}).get("project") or {}
    return (proj.get("dataProcessingProtocol") or "") + " " + (proj.get("sampleProcessingProtocol") or "")

def labeling(pxd):
    p = AGG % pxd
    if not os.path.exists(p):
        return None
    return ((json.load(open(p)).get("runAssessor") or {}).get("search_criteria") or {}).get("labeling")

print(f"HAMLET SDRFs scanned: {len(SDRFS)}\n")

fp = tp = unk = 0
affected = []
for f in SDRFS:
    if "UNIMOD:34;MT=Variable;TA=KR" not in open(f).read():
        continue
    pxd = os.path.basename(f).replace(".sdrf.tsv", "")
    affected.append(pxd)
    t = protocol_text(pxd)
    if not t or not t.strip():
        unk += 1
    elif OLD.search(t) and not NEW.search(t):
        fp += 1
    elif NEW.search(t):
        tp += 1
    else:
        unk += 1
print("Part 3  wrong Methyl mod NT=Methyl;AC=UNIMOD:34;MT=Variable;TA=KR")
print(f"  SDRFs carrying it                                        : {len(affected)}")
print(f"  false positive (matched only inside 'carbamidomethylat') : {fp}")
print(f"  genuine ('methylation' as its own word)                  : {tp}")
print(f"  undetermined (no PRIDE protocol text stored)             : {unk}\n")

rows_eq = 0
gain = []
lab = Counter()
for f in SDRFS:
    rr = list(csv.DictReader(open(f), delimiter="\t"))
    if not rr:
        continue
    pxd = os.path.basename(f).replace(".sdrf.tsv", "")
    nfiles = len({(r.get("comment[data file]") or "").strip() for r in rr})
    if len(rr) == nfiles:
        rows_eq += 1
    lab[(rr[0].get("comment[label]") or "").strip()] += 1
    key = str(labeling(pxd) or "").lower().strip().replace("-", "").replace(" ", "")
    n = CHANNEL_COUNT.get(key)
    if n and n > 1:
        gain.append((pxd, key, nfiles, len(rr), nfiles * n))
print("Part 4  multiplex channel rows")
print(f"  SDRFs where rows == n data files (no expansion)          : {rows_eq}/{len(SDRFS)}")
print(f"  SDRFs whose detected label maps to >1 channel            : {len(gain)}")
print(f"  total rows in those SDRFs, now -> after expansion        : "
      f"{sum(g[3] for g in gain)} -> {sum(g[4] for g in gain)}")
print("\n  per dataset:")
print(f"  {'PXD':12s} {'label':10s} {'files':>5s} {'now':>5s} {'after':>6s}")
for pxd, key, nf, now, aft in sorted(gain):
    print(f"  {pxd:12s} {key:10s} {nf:5d} {now:5d} {aft:6d}")
print("\n  comment[label] values currently emitted across the store:")
for k, v in lab.most_common():
    print(f"    {v:5d}  {k!r}")
