"""Build data/es/geography.csv from raw downloads.

Usage: python3 -I build_geography.py <data_dir>
  <data_dir>/raw/mitma_atlas/refdata_mun.json, refdata_gau.json  (MIVAU Atlas Digital de las Areas Urbanas)
  <data_dir>/raw/ine_api/munAM_<table>.json                       (INE DPOP municipal tables, 1 Jan 2025)
  <data_dir>/raw/geonames/extracted/ES.txt                         (GeoNames postal codes)
"""
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

D = Path(sys.argv[1])

# metro -> (province code, INE province name, natural-order region name, INE DPOP table, Atlas GAU code, min population)
METROS = [
    ("Madrid", "28", "Madrid", "2881", "01", 20000),
    ("Barcelona", "08", "Barcelona", "2861", "02", 20000),
    ("Valencia", "46", "Valencia/València", "2903", "03", 20000),
    ("Bilbao", "48", "Bizkaia", "2905", "05", 20000),
    ("Sevilla", "41", "Sevilla", "2895", "04", 20000),
    ("Málaga", "29", "Málaga", "2882", "06", 20000),
    ("Santiago de Compostela", "15", "A Coruña", "2868", "45", 5000),
]
CORE_CODES = {"Madrid": "28079", "Barcelona": "08019", "Valencia": "46250", "Bilbao": "48020",
              "Sevilla": "41091", "Málaga": "29067", "Santiago de Compostela": "15078"}

ARTICLES = ["El", "La", "Los", "Las", "L'", "Els", "Les", "A", "O", "As", "Os", "Es", "Sa", "Ses", "S'"]


def natural_order(name):
    """INE writes 'Rozas de Madrid, Las' -> 'Las Rozas de Madrid'; handles each '/' part."""
    parts = []
    for part in name.split("/"):
        m = re.match(r"^(.*), (" + "|".join(re.escape(a) for a in ARTICLES) + r")$", part)
        if m:
            base, art = m.group(1), m.group(2)
            part = art + base if art.endswith("'") else f"{art} {base}"
        parts.append(part)
    return "/".join(parts)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# --- Atlas membership
mun = json.load(open(D / "raw/mitma_atlas/refdata_mun.json", encoding="utf-8"))["content"]["territories"]
gau = json.load(open(D / "raw/mitma_atlas/refdata_gau.json", encoding="utf-8"))["content"]["territories"]
gau_name = dict(zip(gau["codgeo"], gau["libgeo"]))
members = defaultdict(list)
atlas_name = {}
for code, lib, g in zip(mun["codgeo"], mun["libgeo"], mun["gau"]):
    members[g].append(code)
    atlas_name[code] = lib

# --- INE population 1 Jan 2025
pop, ine_name, prov_total = {}, {}, {}
for metro, pcode, region, table, gcode, _ in METROS:
    series = json.load(open(D / f"raw/ine_api/munAM_{table}.json", encoding="utf-8"))
    for s in series:
        md = {m["T3_Variable"]: m for m in s["MetaData"]}
        if md["Sexo"]["Nombre"] != "Total":
            continue
        if not s["Data"]:
            continue  # series with no 2025 value (e.g. municipality no longer existing)
        data = s["Data"][0]
        assert data["Anyo"] == 2025 and data["Fecha"].startswith("2025-01-01"), s["Nombre"]
        if "Municipios" in md:
            c = md["Municipios"]["Codigo"]
            pop[c] = int(data["Valor"])
            ine_name[c] = md["Municipios"]["Nombre"]
        elif "Provincias" in md:
            prov_total[md["Provincias"]["Codigo"]] = int(data["Valor"])

# --- GeoNames postal codes
# Assignment rule (per GeoNames row, only rows whose postal code starts with one of our province codes):
#  1. if the place name equals (accent/case-insensitive) the name of exactly one INE municipality of
#     that province -> assign to that municipality (overrides GeoNames admin3 code, which is
#     sometimes the neighbouring municipality, e.g. 41500 'Alcala De Guadaira' coded 41091 Sevilla);
#  2. else, if admin3 code is present and starts with the same province code -> assign to admin3 code;
#  3. else leave unassigned.
PROVS = {m[1] for m in METROS}
name_index = defaultdict(set)
for c, n in ine_name.items():
    variants = {n, natural_order(n)}
    for part in n.split("/"):
        variants |= {part, natural_order(part)}
    for v in variants:
        name_index[(c[:2], norm(v))].add(c)

pc_rows = defaultdict(list)          # muni code -> [(pc, lat, lon, place)]
warnings = []
overrides, unassigned_n, foreign_n = [], 0, []
moved = {}   # (postal code, wrong admin3, lat, lon) -> corrected municipality
with open(D / "raw/geonames/extracted/ES.txt", encoding="utf-8") as f:
    for line in f:
        r = line.rstrip("\n").split("\t")
        cc, pc, place, a1, a1c, a2, a2c, a3, a3c, lat, lon = r[:11]
        prov = pc[:2]
        if prov not in PROVS:
            if a3c[:2] in PROVS:
                foreign_n.append(f"{pc} '{place}' admin3={a3c}")
            continue
        cand = name_index.get((prov, norm(place)), set())
        if len(cand) == 1:
            target = next(iter(cand))
            if a3c and a3c != target:
                overrides.append(f"{pc} '{place}': admin3 {a3c} -> {target}")
                moved[(pc, a3c, lat, lon)] = target
        elif a3c and a3c[:2] == prov:
            target = a3c
        else:
            if a3c:
                foreign_n.append(f"{pc} '{place}' admin3={a3c}")
            unassigned_n += 1
            continue
        pc_rows[target].append((pc, float(lat), float(lon), place))

# --- IGN Nomenclator (api-features.ign.es collection 'nuc'): municipal capital nucleus point
# capital flag is a 6-char string; 4th char '1' = capital of municipality.
ign_cap = defaultdict(list)
for fp in sorted((D / "raw/ign").glob("nuc_*_*.json")):
    for ft in json.load(open(fp, encoding="utf-8"))["features"]:
        pr = ft["properties"]
        if len(pr["capital"]) == 6 and pr["capital"][3] == "1":
            ign_cap[pr["codine"][:5]].append(pr)

def km(a, b):
    import math
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))

coord_src = defaultdict(int)
# IGN nucleus names per municipality (used to veto the second-pass move below)
ign_names = defaultdict(set)
for fp in sorted((D / "raw/ign").glob("nuc_*_*.json")):
    for ft in json.load(open(fp, encoding="utf-8"))["features"]:
        pr = ft["properties"]
        ign_names[pr["codine"][:5]].add(norm(pr["nombre"]))

def base_place(place):
    return norm(re.sub(r"\(.*?\)", "", place))

# Second pass: other rows of the same postal code that GeoNames geocoded to exactly the same point
# and coded to the same (overridden) admin3 share the same misattribution -> move them too.
moved_rows = []
for (pc, wrong, lat, lon), target in moved.items():
    keep = []
    for row in pc_rows.get(wrong, []):
        same_pt = row[0] == pc and (f"{row[1]}", f"{row[2]}") == (str(float(lat)), str(float(lon)))
        if same_pt and base_place(row[3]) in ign_names[wrong]:
            moved_rows.append(f"{pc} '{row[3]}': NOT moved - IGN lists a nucleus of that name in {wrong}")
            keep.append(row)
        elif same_pt:
            pc_rows[target].append(row)
            moved_rows.append(f"{pc} '{row[3]}': admin3 {wrong} -> {target} (same point as overridden row)")
        else:
            keep.append(row)
    pc_rows[wrong] = keep

out_rows, report = [], []
for metro, pcode, region, table, gcode, minpop in METROS:
    assert gau_name[gcode] == metro, (gcode, gau_name[gcode], metro)
    codes = members[gcode]
    sel = []
    for c in codes:
        if c not in pop:
            warnings.append(f"{metro}: Atlas member {c} {atlas_name.get(c)} not in INE table {table} (other province?)")
            continue
        if c == CORE_CODES[metro] or pop[c] >= minpop:
            sel.append(c)
    assert CORE_CODES[metro] in sel
    sel.sort(key=lambda c: (c != CORE_CODES[metro], -pop[c]))
    tot = 0
    for c in sel:
        name = natural_order(ine_name[c])
        by_pc = defaultdict(list)
        for pc, lat, lon, place in pc_rows.get(c, []):
            by_pc[pc].append((lat, lon))
        pcs = sorted(by_pc)
        bad = [p for p in pcs if not p.startswith(pcode)]
        assert not bad, (c, bad)
        gn = None
        if not pcs:
            warnings.append(f"{c} {name}: no postal codes in GeoNames")
        else:
            # GeoNames: per postal code mean, then mean over postal codes (fallback / diagnostic only)
            pts = [(sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for v in by_pc.values()]
            gn = (sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts))
        caps = ign_cap.get(c, [])
        if len(caps) > 1:
            names = [(x["nombre"], x["habitantes"]) for x in caps]
            caps = [max(caps, key=lambda x: x["habitantes"])]
            warnings.append(f"{c} {name}: {len(names)} IGN capital nuclei {names} -> used most populous '{caps[0]['nombre']}'")
        if len(caps) == 1:
            pt = (caps[0]["latitud"], caps[0]["longitud"])
            coord_src["IGN capital nucleus"] += 1
            if gn and km(pt, gn) > 5:
                warnings.append(f"{c} {name}: GeoNames postal-code mean is {km(pt, gn):.1f} km from IGN capital '{caps[0]['nombre']}'")
        elif gn:
            pt = gn
            coord_src["GeoNames postal-code mean"] += 1
            warnings.append(f"{c} {name}: {len(caps)} IGN capital nuclei -> used GeoNames mean")
        else:
            pt = None
            warnings.append(f"{c} {name}: NO coordinates")
        lat, lon = (f"{pt[0]:.5f}", f"{pt[1]:.5f}") if pt else ("", "")
        if norm(atlas_name[c]) != norm(ine_name[c]):
            warnings.append(f"name differs Atlas '{atlas_name[c]}' vs INE '{ine_name[c]}' ({c})")
        out_rows.append([region, pcode, metro, name, c, "|".join(pcs), lat, lon, pop[c]])
        tot += pop[c]
    report.append((metro, len(codes), len(sel), tot, prov_total.get(pcode)))

out = D / "es/geography.csv"
with open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["region", "region_code", "city", "municipality", "municipality_code", "postal_codes", "lat", "lon", "population"])
    w.writerows(out_rows)

print(f"wrote {out} rows={len(out_rows)} coord sources={dict(coord_src)}")
for metro, n_atlas, n_sel, tot, ptot in report:
    print(f"{metro:24s} atlas_members={n_atlas:3d} selected={n_sel:3d} pop_sum_2025={tot:>9,d} province_total_2025={ptot:>9,d}")
for w_ in warnings:
    print("WARN", w_)
print(f"GeoNames rows in target provinces left unassigned: {unassigned_n}")
print(f"GeoNames rows skipped (postal-code prefix != admin3 province): {len(foreign_n)}")
for x in foreign_n:
    print("  SKIP", x)
print(f"GeoNames rows moved with an overridden row (same point): {len(moved_rows)}")
for x in moved_rows:
    print("  MOVED", x)
print(f"GeoNames admin3 overrides by place-name match: {len(overrides)}")
for x in overrides:
    print("  OVR", x)
