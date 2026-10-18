"""Build data/es/population_by_age_sex.csv from INE ECP table 56945 (single year of age, province, sex).

Usage: python3 -I build_age_sex.py <data_dir>
Inputs: <data_dir>/raw/ine_api/ecp56945_prov<valueId>.json   (DATOS_TABLA/56945?tv=115:<id>&nult=1&tip=AM)
        <data_dir>/raw/ine_api/munAM_<table>.json           (Padron 1 Jan 2025 province totals, for comparison)
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

D = Path(sys.argv[1])
REF_DATE = "2025-01-01"
# region_code, region (natural order), INE value id in table 56945, Padron DPOP table
PROVS = [("28", "Madrid", 29, "2881"), ("08", "Barcelona", 9, "2861"), ("46", "Valencia/València", 46, "2903"),
         ("48", "Bizkaia", 48, "2905"), ("41", "Sevilla", 41, "2895"), ("29", "Málaga", 30, "2882"),
         ("15", "A Coruña", 16, "2868")]
SEX = {"Hombres": "M", "Mujeres": "F", "Total": "T"}

rows, checks = [], []
for code, region, vid, dpop in PROVS:
    series = json.load(open(D / f"raw/ine_api/ecp56945_prov{vid}.json", encoding="utf-8"))
    single = defaultdict(int)       # (sex, age or 100) -> count
    totals = {}
    for s in series:
        md = {m["T3_Variable"]: m for m in s["MetaData"]}
        assert md["Provincias"]["Codigo"] == code, s["Nombre"]
        assert md["Conceptos demógraficos"]["Nombre"] == "Población"
        assert len(s["Data"]) == 1
        dat = s["Data"][0]
        assert dat["Fecha"].startswith(REF_DATE) and dat["T3_TipoDato"] == "Definitivo", (s["Nombre"], dat)
        sex = SEX[md["Sexo"]["Nombre"]]
        val = int(dat["Valor"])
        if "Totales de edad" in md:
            totals[sex] = val
            continue
        if "Semiintervalos de edad" in md:
            age_name = md["Semiintervalos de edad"]["Nombre"]
            if age_name != "100 y más años":
                continue  # open interval e.g. '85 y más años' is redundant with single ages
        else:
            age_name = md["Valores simples de edad"]["Nombre"]
        if age_name == "100 y más años":
            age = 100
        else:
            m = re.fullmatch(r"(\d+) años?", age_name)
            assert m, age_name
            age = int(m.group(1))
            assert age <= 99
        single[(sex, age)] += val
    for sex in ("M", "F", "T"):
        assert sorted(a for (sx, a) in single if sx == sex) == list(range(101)), (code, sex)
    # Padron official province total (1 Jan 2025)
    padron = {}
    for s in json.load(open(D / f"raw/ine_api/munAM_{dpop}.json", encoding="utf-8")):
        md = {m["T3_Variable"]: m for m in s["MetaData"]}
        if "Provincias" in md and s["Data"]:
            padron[SEX[md["Sexo"]["Nombre"]]] = int(s["Data"][0]["Valor"])
    sums = {}
    for sex in ("M", "F"):
        tot = 0
        for lo in range(0, 100, 5):
            v = sum(single[(sex, a)] for a in range(lo, lo + 5))
            rows.append([code, region, sex, lo, lo + 4, v])
            tot += v
        v = single[(sex, 100)]
        rows.append([code, region, sex, 100, "", v])
        tot += v
        sums[sex] = tot
    checks.append((code, region, sums, totals, padron))

out = D / "es/population_by_age_sex.csv"
with open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["region_code", "region", "sex", "age_low", "age_high", "population"])
    w.writerows(rows)
print(f"wrote {out} rows={len(rows)}")
for code, region, sums, totals, padron in checks:
    s_all = sums["M"] + sums["F"]
    print(f"{code} {region:18s} sum_bands M={sums['M']:,} F={sums['F']:,} total={s_all:,} | "
          f"ECP published total M={totals['M']:,} F={totals['F']:,} T={totals['T']:,} "
          f"match={sums['M'] == totals['M'] and sums['F'] == totals['F'] and s_all == totals['T']} | "
          f"Padron 2025 official total={padron['T']:,} (diff ECP-Padron={totals['T'] - padron['T']:+,})")
