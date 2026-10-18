"""Build given-name and surname CSVs from INE 'Nombres y apellidos' files.
usage: build_names.py <nombres_por_edad_media.xlsx> <apellidos_frecuencia.xls> <outdir>
"""
import sys, csv, re, unicodedata
import openpyxl, xlrd

PARTICLES = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "I"}
TOP = 300

def cap_token(tok):
    # capitalise each hyphen/apostrophe-separated segment: first char upper, rest lower
    parts = re.split(r"([-'])", tok)
    return "".join(p[:1].upper() + p[1:].lower() if p not in ("-", "'") else p for p in parts)

def title(s):
    words = s.split()
    out = []
    for w in words:
        out.append(w.lower() if w in PARTICLES else cap_token(w))
    return " ".join(out)

def nonascii_report(label, rows):
    na = [r[0] for r in rows if any(ord(ch) > 127 for ch in r[0])]
    print(f"{label}: non-ASCII raw values in selection: {na}")

def names(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    hdr_seen = False; rows = []; ref = None
    for row in ws.iter_rows(values_only=True):
        if row[0] and isinstance(row[0], str) and "fecha" in row[0]: ref = row[0]
        if row[0] == "Orden": hdr_seen = True; continue
        if hdr_seen and row[1] and isinstance(row[2], (int, float)):
            rows.append((str(row[1]).strip(), int(row[2]), row[3]))
    print(sheet, "ref:", ref, "rows:", len(rows))
    rows.sort(key=lambda r: -r[1])
    return rows

def surnames(path):
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    print("surname sheet:", sh.name, "|", sh.cell_value(2, 0))
    rows = []
    for r in range(5, sh.nrows):
        name = sh.cell_value(r, 1); f1 = sh.cell_value(r, 2); f2 = sh.cell_value(r, 3)
        if isinstance(name, str) and name.strip() and isinstance(f1, float):
            rows.append((name.strip(), int(f1), int(f2) if isinstance(f2, float) else None))
    print("surname rows:", len(rows))
    rows.sort(key=lambda r: -r[1])
    return rows

def main():
    nfile, sfile, outdir = sys.argv[1:4]
    for sheet, fn in (("Hombres", "given_names_male.csv"), ("Mujeres", "given_names_female.csv")):
        rows = names(nfile, sheet)[:TOP]
        nonascii_report(sheet, rows)
        with open(f"{outdir}/{fn}", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["name", "frequency"])
            for n, f, _ in rows: w.writerow([title(n), f])
        print(fn, "top5:", [(title(n), f) for n, f, _ in rows[:5]], "min freq:", rows[-1][1])
    rows = surnames(sfile)[:TOP]
    nonascii_report("surnames", rows)
    assert all(r[2] is not None for r in rows)
    with open(f"{outdir}/surnames.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["surname", "first_frequency", "second_frequency"])
        for n, f1, f2 in rows: w.writerow([title(n), f1, f2])
    print("surnames top5:", [(title(n), a, b) for n, a, b in rows[:5]], "min:", rows[-1][1])
    multi = [title(n) for n, *_ in rows if " " in n or "-" in n or "'" in n]
    print("surnames with spaces/hyphens/apostrophes:", multi)

main()
