# Spain locale pack - data build scripts

These scripts turned the public downloads listed in
`src/synthea/resources/locale/es/RESOURCES.md` into the CSV files the `es` pack
ships. They are kept so the data can be traced and regenerated when a source is
updated (ISO 13485 4.2 traceability); they are not run at generation time.

| Script | Builds | Inputs (see RESOURCES.md for URLs, versions, licences) |
|---|---|---|
| `build_geography.py <data_dir>` | `geography.csv` | MIVAU Atlas de las Áreas Urbanas (2021), INE Padrón 1 Jan 2025, GeoNames ES postal codes, IGN settlements |
| `build_age_sex.py <data_dir>` | `population_by_age_sex.csv` | INE Estadística Continua de Población, table 56945 |
| `build_names.py ...` | `names/*.csv` | INE frequent given names and surnames, 1 Jan 2025 |
| `build_nationality.py ...` | `nationality.csv` | INE table 59591 |
| `build_marital.py <src> <src20> <outdir>` | `marital_status.csv` | INE census table 76288 |
| `build_cohort_fertility.py <src> <src1407> <outdir>` | calibration evidence for `calibration.reproduction.exposure` | INE tables 1406 / 1407 |

Raw downloads are not committed (about 80 MB); fetch them again from the
sources in RESOURCES.md. Run with `python3 -I <script> ...` from an empty
working directory, since the inputs are third-party files.
