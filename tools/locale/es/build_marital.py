"""Marital status shares from INE Censo de Población (annual) table 76288 (16+), Spain total.
usage: build_marital.py <censop_76288.json> <censop_76273_nult1.json> <outdir>
"""
import sys, json, csv
src, src20, outdir = sys.argv[1:4]
d = json.load(open(src))
MAP = {"Soltero/a": ("S", "Never Married"), "Casado/a": ("M", "Married"),
       "Viudo/a": ("W", "Widowed"), "Divorciado/a o separado/a": ("D", "Divorced")}
vals = {}; year = None
for s in d:
    p = [x.strip() for x in s["Nombre"].split(".") if x.strip()]
    if p[0] == "Total" and p[1] == "Total" and p[-1] == "Total Nacional":
        latest = max(s["Data"], key=lambda x: x["Anyo"])
        vals[p[2]] = latest["Valor"]; year = latest["Anyo"]
print("year", year, vals)
known = sum(vals[k] for k in MAP)
assert abs(known + vals["No consta"] - vals["Total"]) < 1, "categories do not add up"
print("No consta share of total:", vals["No consta"] / vals["Total"])
raw = {k: vals[k] / known for k in MAP}
rounded = {k: round(v, 4) for k, v in raw.items()}
diff = round(1 - sum(rounded.values()), 4)
big = max(rounded, key=rounded.get); rounded[big] = round(rounded[big] + diff, 4)
print("rounding adjustment applied to", big, diff)
with open(f"{outdir}/marital_status.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["code", "display", "share"])
    for k, (code, disp) in MAP.items():
        w.writerow([code, disp, f"{rounded[k]:.4f}"])
print({MAP[k][0]: (round(raw[k], 6), rounded[k]) for k in MAP}, "sum", round(sum(rounded.values()), 6))
# comparison: 20+ from table 76273 (latest year in the nult=1 extract)
d2 = json.load(open(src20)); tot20 = {}
for s in d2:
    p = [x.strip() for x in s["Nombre"].split(".") if x.strip()]
    if p[1] == "Total" and p[2] == "Total" and p[-1] == "Total Nacional" and p[0] not in ("16 y más años",):
        tot20.setdefault(p[4], 0); 
        if p[0] != "De 16 a 19 años": tot20[p[4]] += s["Data"][0]["Valor"]
k20 = sum(tot20[k] for k in MAP)
print("20+ comparison (year", d2[0]["Data"][0]["Anyo"], "):", {MAP[k][0]: round(tot20[k] / k20, 4) for k in MAP}, "no consta 20+:", round(tot20["No consta"] / (k20 + tot20["No consta"]), 4))
