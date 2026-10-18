"""Population by nationality (Spanish/foreign) from INE ECP table 59591 (PROV), latest date.
usage: build_nationality.py <ecp_59591.json> <outdir>
"""
import sys, json, csv
src, outdir = sys.argv[1:3]
d = json.load(open(src))
TARGET = [("00", "Total Nacional", "España"), ("28", "Madrid", "Madrid"), ("08", "Barcelona", "Barcelona"),
          ("46", "Valencia/València", "Valencia/València"), ("48", "Bizkaia", "Bizkaia"),
          ("41", "Sevilla", "Sevilla"), ("29", "Málaga", "Málaga"), ("15", "Coruña, A", "A Coruña")]
vals = {}
for s in d:
    p = [x.strip() for x in s["Nombre"].split(".") if x.strip()]
    if p[0] == "Total Nacional" and p[2] == "Todas las edades" and p[3] == "Total":
        nat = p[1]  # national series order: geo. nationality. age. sex
    elif p[1] == "Todas las edades" and p[3] == "Total":
        nat = p[2]  # provincial series order: geo. age. nationality. sex
    else:
        continue
    if True:
        latest = max(s["Data"], key=lambda x: x["Fecha"])
        vals[(p[0], nat)] = (latest["Valor"], latest["Fecha"], latest.get("T3_TipoDato"))
geos = sorted({g for g, _ in vals}); print("geos with data:", len(geos))
rows = []
for code, ine_name, label in TARGET:
    t, e, x = (vals[(ine_name, k)] for k in ("Total", "Española", "Extranjera"))
    assert t[1] == e[1] == x[1]
    assert t[0] == e[0] + x[0], (ine_name, t, e, x)
    rows.append([code, label, int(t[0]), int(e[0]), int(x[0])])
    print(code, label, t[1], t[2], int(t[0]), int(e[0]), int(x[0]), "foreign share %.4f" % (x[0] / t[0]))
with open(f"{outdir}/nationality.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["region_code", "region", "total", "spanish", "foreign"]); w.writerows(rows)
