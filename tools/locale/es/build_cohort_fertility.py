"""Derive cumulative cohort fertility from INE IDB table 1406 (age-specific fertility
rates per 1000 women, single completed age, both nationalities, all birth orders).
Lexis: rate f(a,t) (completed age a, calendar year t) covers cohorts t-a and t-a-1.
CCF(c) = sum_a 0.5*[f(a,c+a) + f(a,c+a+1)] / 1000.
usage: build_cohort_fertility.py <idb_1406.json> <idb_1407.json> <outdir>
"""
import sys, json, re, csv
src, src1407, outdir = sys.argv[1:4]
d = json.load(open(src))
rates = {}  # (age, year) -> per-1000
for s in d:
    parts = [p.strip() for p in s["Nombre"].split(".") if p.strip()]
    if len(parts) != 3 or parts[1] != "Total Nacional":
        continue
    m = re.match(r"(\d+)", parts[2]); age = int(m.group(1))
    for x in s["Data"]:
        if x["Valor"] is not None:
            rates[(age, x["Anyo"])] = x["Valor"]
ages = sorted({a for a, _ in rates}); years = sorted({t for _, t in rates})
print("ages", ages[0], "..", ages[-1], "years", years[0], "..", years[-1])
# validation: period sum per year should match ICF (table 1407 IDB72160)
icf = {x["Anyo"]: x["Valor"] for s in json.load(open(src1407)) if s["COD"] == "IDB72160" for x in s["Data"]}
for t in (1975, 1990, 2008, 2023, 2024):
    print("check year", t, "sum f/1000 =", round(sum(rates[(a, t)] for a in ages) / 1000, 3), "ICF(1407) =", icf.get(t))
complete, partial = [], []
for c in range(1958, 1986):
    tot = 0.0; missing = []; last_full = None
    for a in ages:
        for t in (c + a, c + a + 1):
            if (a, t) in rates: tot += 0.5 * rates[(a, t)]
            else: missing.append((a, t))
        if (a, c + a) in rates and (a, c + a + 1) in rates: last_full = a
    ccf = tot / 1000
    print(c, round(ccf, 3), "missing:", missing[:3], "... n=", len(missing), "last full age:", last_full)
    if not missing:
        complete.append((c, ccf, "", ""))
    elif all(a == ages[-1] for a, _ in missing) and len(missing) == 1:
        # only the second half-term of the open 49+ group is missing (year c+50 not yet published)
        complete.append((c, ccf, f"excludes 0.5*f(49+,{missing[0][1]}) not yet published", ""))
    elif all(t > years[-1] for _, t in missing):
        partial.append((c, ccf, last_full))
with open(f"{outdir}/completed_fertility.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["birth_cohort", "children_per_woman"])
    for c, v, note, _ in complete:
        if 1960 <= c <= 1980: w.writerow([c, f"{v:.3f}"])
with open(f"{outdir}/cohort_fertility_partial.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["birth_cohort", "cumulative_children_per_woman", "last_age_both_lexis_halves_observed"])
    for c, v, la in partial:
        if c <= 1980: w.writerow([c, f"{v:.3f}", la])
print("notes:", [(c, n) for c, _, n, _ in complete if n])
