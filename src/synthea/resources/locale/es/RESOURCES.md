# Spain (`es`) locale pack: data provenance

Every file in this directory is listed here with where it came from, its
reference date, its licence and how it was transformed. All data was fetched
on **2026-10-18**. Nothing was typed in by hand except the files marked
*fictional* or *authored*, which contain no statistics.

The fetch and transformation scripts are not shipped. They live with the
pull request that added this pack. Each transformation below is described
precisely enough to repeat it.

## Licences and required attribution

- **INE** (Instituto Nacional de Estadística). Licence: CC BY 4.0, per the
  INE legal notice (<https://www.ine.es/aviso_legal>):
  > La licencia de uso general a aplicar a la información estadística de este
  > sitio web, salvo que se indique lo contrario, es la Creative Commons
  > Reconocimiento 4.0 (CC BY 4.0) [...] Debe citarse la fuente [...]
  > "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
  > en caso de que se realice tratamiento de los datos. Debe mencionarse la
  > fecha de la última actualización [...] No se podrá indicar, insinuar o
  > sugerir que el INE participa, patrocina o apoya la reutilización [...]

  Every INE-derived file here is processed data, so the attribution is
  **"Elaboración propia con datos extraídos del sitio web del INE:
  www.ine.es"**, followed by the last-update date given for each file. INE
  does not participate in, sponsor or endorse this project.
- **GeoNames** postal codes. Licence: CC BY 4.0 ("you can use the dump as long
  as you give credit to geonames"). Attribution: *Postal codes: GeoNames
  (www.geonames.org), CC BY 4.0*.
- **IGN / CNIG** *Información Geográfica de Referencia - Poblaciones*.
  Licence: CC BY 4.0 (Orden FOM/2807/2015). Attribution: *Obra derivada de
  Poblaciones (IGR) 2025 CC-BY 4.0 ign.es*.
- **MIVAU** *Atlas Digital de las Áreas Urbanas*. Only the factual
  municipality-to-urban-area grouping is used. **The reuse terms could not be
  retrieved**: the ministry's legal-notice pages returned HTTP 403, and the
  Atlas shows only "© Ministerio de Vivienda y Agenda Urbana". This needs
  checking before any redistribution beyond this repository.

---

## `geography.csv`

132 municipalities, one per row, in the pack geography format.

- **Membership (`city`).** Each municipality belongs to one of seven urban
  areas, taken from the MIVAU *Atlas Digital de las Áreas Urbanas*, Grandes
  Áreas Urbanas, 2021 delimitation. Sources:
  `https://atlasau.mitma.gob.es/GC_refdata.php?nivgeo=mun&extent=extent0&lang=es`
  and the methodology document `Metodologia_delimitacion_AU_2021.pdf`. The
  GAU codes used are 01 Madrid, 02 Barcelona, 03 Valencia, 05 Bilbao,
  04 Sevilla, 06 Málaga and 45 Santiago de Compostela.

  A municipality is kept if its population is at least 20,000, plus the core
  city of each area. Santiago de Compostela uses a 5,000 threshold, because
  its area is small.

  | Area | In the GAU | Kept | Population |
  |---|---|---|---|
  | Madrid | 52 | 36 | 6,445,446 |
  | Barcelona | 165 | 45 | 4,615,913 |
  | Valencia | 45 | 18 | 1,447,421 |
  | Bilbao | 35 | 10 | 772,116 |
  | Sevilla | 24 | 12 | 1,193,535 |
  | Málaga | 8 | 8 | 1,055,898 |
  | Santiago de Compostela | 3 | 3 | 153,209 |

- **Population.** INE *Cifras oficiales de población de los municipios
  españoles: Revisión del Padrón Municipal*, 1 January 2025 (definitive,
  RD 1117/2025). Provincial tables 2881 (Madrid), 2861 (Barcelona),
  2903 (Valencia), 2905 (Bizkaia), 2895 (Sevilla), 2882 (Málaga) and
  2868 (A Coruña), via
  `https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/<id>?nult=1&tip=AM`.
  Last updated 2025-12-11. The `population` column is the Sexo = Total
  series, and `municipality_code` is INE's five-digit code.
- **Names.** INE's official municipality names are used, with any postposed
  article moved to the front ("Rozas de Madrid, Las" becomes "Las Rozas de
  Madrid"). Bilingual names are kept as INE writes them ("València").
  "Coruña, A" becomes "A Coruña".
- **Postal codes.** From GeoNames `https://download.geonames.org/export/zip/ES.zip`
  (dump of 2026-10-18), with 531 codes in all. GeoNames' own municipality
  code is wrong for some rows (e.g. 41500 Alcalá de Guadaíra is coded as
  Sevilla), so codes were assigned as follows:
  1. A row whose place name matches exactly one INE municipality of the
     province, ignoring accents and case, goes to that municipality.
  2. Otherwise the row goes to its GeoNames municipality code, if that code
     is in the same province.
  3. Rows sharing a moved postal code and map point follow the moved row.
  4. Unmatched rows are dropped.

  Every code starts with the province code; this is checked. 28250 appears
  under both Torrelodones and Galapagar. GeoNames coverage may be incomplete,
  and some municipalities have only one code.
- **Coordinates.** The point of the municipality's capital nucleus, from the
  IGN OGC API Features collection `nuc`
  (`https://api-features.ign.es/collections/nuc/items`, feature dates
  2025-11). The capital nucleus is the one whose `capital` flag has '1' in
  its fourth character. Galdakao and Erandio each have two flagged nuclei;
  the more populous was used for both. Rivas-Vaciamadrid's official capital,
  Vaciamadrid, is about 5 km from the main town. Homes are placed within the
  default 2 km of this point.

## `population_by_age_sex.csv`

294 rows: 7 provinces, 2 sexes and 21 bands (0-4 ... 95-99, then 100+).

- **Source.** INE *Estadística Continua de Población* (ECP), table **56945**
  "Población residente por fecha, sexo y edad", provincial, single years of
  age, 1 January 2025 (definitive). Fetched via
  `https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/56945?tv=115:<province>&nult=1&tip=AM`.
  Last updated 2025-12-02.
- **Why the ECP.** The Padrón continuo by five-year band (operation 188)
  ends at 1 January 2022. The ECP is INE's current population by province,
  sex and age.
- **Transformation.** Single years 0-99 were summed into five-year bands;
  "100 y más" became the open band (`age_high` left empty). For every
  province and sex, the bands sum exactly to the ECP total.
- **Caveat.** The ECP (resident population) and the Padrón revision (used by
  `geography.csv`) are different statistics. Their provincial totals differ
  by at most 23,384 people (Barcelona).

## `names/given_names_male.csv`, `names/given_names_female.csv`, `names/surnames.csv`

300 rows each.

- **Source.** INE *Estadística de nombres y apellidos*. Files:
  - `https://www.ine.es/daco/daco42/nombyapel/nombres_por_edad_media.xlsx`
  - `https://www.ine.es/daco/daco42/nombyapel/apellidos_frecuencia.xls`

  Both are from the annual Censo de población of 1 January 2025 and were
  last modified on 2026-04-23. The older `.xls` names files still linked from
  INE hold 2022 data and were not used.
- **Transformation.** The top 300 entries were kept by national frequency
  (for surnames, by frequency as first surname). `first_frequency` and
  `second_frequency` are INE's "Apellido 1º" and "Apellido 2º" totals.

  INE publishes names in upper case **without acute accents but with Ñ**.
  Each word was title-cased and the particles de, del, la, las, los, y and i
  were lower-cased. **No accents were added**, because INE does not supply
  them. So names read "Maria", "Jose" and "Garcia", while "Muñoz" keeps
  its Ñ.
- **Use.** Each person draws a given name by sex, a first surname and a
  second surname, each weighted by its INE frequency. Clinicians are named
  the same way. Street names reuse the surname list.

## `marital_status.csv`

- **Source.** INE *Censo de Población* (annual), table **76288** "Población
  de 16 y más años por sexo y estado civil", Spain, 1 January 2024. Last
  updated 2025-12-02.
- **Transformation.** "No consta" (4.6%) was excluded and the rest
  renormalised, then mapped to HL7 v3 codes: Soltero/a S 0.3658, Casado/a
  M 0.4797, Viudo/a W 0.0732, "Divorciado/a o separado/a" D 0.0813.
- **Gaps.** INE does not separate divorced from separated, so there is no
  `L` row. 16+ is the closest adult cut INE publishes; the engine assigns
  marital status at 18.

## `nationality.csv`

- **Source.** INE ECP table **59591** "Población residente por fecha, sexo,
  grupo de edad y nacionalidad (española/extranjera)", 1 July 2026, which
  INE marks **provisional**. Last updated 2026-08-06.
- **Use.** The foreign-national share of the patient's province (Spain
  14.93%; Madrid 17.07%, Barcelona 18.69%, Valencia 17.33%, Bizkaia 10.47%,
  Sevilla 6.47%, Málaga 19.93%, A Coruña 7.27%) decides whether a person
  carries an NIE (foreign national) or a DNI (Spanish national).

## `providers/hospitals.csv` (fictional)

One **fictional** hospital per area, named "TietAI Hospital <city>". These
are not, and do not imitate, any real hospital.

- **Address and phone.** Every hospital's address is "Calle Ficticia TietAI,
  1", which is not a real street. The phone numbers are in the unattributed
  `+34 30X` segment (see *Telephone numbers*).
- **Location.** Coordinates are the core municipality's IGN point offset by
  0.003 degrees. The postal code is the core municipality's first.
- **Size.** The bed counts (600-1,200) and staffing (150-300 clinicians) are
  plausible orders of magnitude for a city's main public hospital. They are
  **illustrative, not statistics**.
- **Service area.** `catchment` is the area name, so every patient of an area
  is treated at its hospital.

## `payers/insurers.csv`, `payers/plans.csv` (authored)

One payer, the Sistema Nacional de Salud, with one plan: universal public
cover from birth (Ley 16/2003, art. 3, as amended by Real Decreto-ley
7/2018).

- **Simplifications.** The plan has no deductible, copay or premium, and the
  payer bears the full cost. Pharmacy co-payment (aportación farmacéutica) is
  **not modelled**.
- **Claims.** The pack declares `produces_claims=False`, so no Claim or
  ExplanationOfBenefit is exported.
- **Costs.** The pack ships no cost tables. Entries are still priced from
  the bundled reference tables (in USD amounts), but those prices are never
  exported, because no claims are produced.

## `templates/notes/note_es.md.j2` (authored)

The Spanish clinical-note template. Section headings and sentences are in
Spanish. Clinical displays come from SNOMED CT, RxNorm and LOINC and remain
in English. The template does not mention race or ethnicity.

---

## Identifiers: all unissuable by construction

The check algorithms come from the Ministerio del Interior, "Cálculo del
dígito de control del NIF/NIE". The live page blocks scripts, so the
Internet Archive capture of 2026-02-28 was used. The formats come from
Real Decreto 183/2004, Annex I (consolidated 2024-09-18).

| Identifier | Format | Why it cannot be real |
|---|---|---|
| DNI | 8 digits and a letter | The letter is never `'TRWAGMYFPDXBNJZSQVHLCKE'[n % 23]`: the valid letter's position is shifted by 1-22. Issued to nationals from age 14 (Ley Orgánica 4/2015, art. 9). |
| NIE | X/Y/Z, 7 digits and a letter | Same check, after the prefix is replaced X→0, Y→1, Z→2, and the letter is always wrong. Issued to foreign nationals. |
| CIP (health card) | 16 characters, `ZZSYN` and 11 digits | The CIP-SNS is officially 16 alphanumeric characters, with no published structure or check. No reserved test range exists, so the format **cannot guarantee** non-collision. The `ZZSYN` prefix is not believed to be issued, and the identifier system marks the value as synthetic. |
| NUSS | 2-digit province, 8 digits, 2 control digits | The control digits are never `(province‖number) mod 97`. This algorithm is de facto (documented by third parties); TGSS publishes none. Issued from age 16; that age is an **assumption** (legal working age), not a statistic. |
| NHC (MRN) | 7 digits | Local to the fictional hospital. |
| Colegiado (practitioner) | `99` and 7 digits | Collegiate numbers begin with a province code from 01 to 52, so 99 is not a province. |

Identifier systems are `urn:tietai:synthea:es:<name>`, deliberately not
official-looking OIDs. The HL7 v2-0203 types used are `NNESP` (DNI), `NI`
(NIE), `JHN` (CIP), `SS` (NUSS), `MR` (NHC) and `PRN` (colegiado).

## Telephone numbers

Spain has **no range reserved for fiction or testing**. Neither the Plan
nacional de numeración telefónica (annex to Real Decreto 2296/2004, BOE-A-2004-21841)
nor the CNMC numbering register has one.

- **Why `+34 30X`.** The plan's section 4.4 lists first digit 3 as
  "pendiente de atribución". The CNMC register `bd-num.zip` (16 October 2026)
  contains no nine-digit assignment starting with 3, and no code of any kind
  starting with 30. So the pack generates `+34 30X XXX XXX`.
- **Why not 0 or 1.** Numbers beginning 0 or 1 are avoided: they are short
  codes and prefixes, including 112.
- **Caveat.** A pending segment can be attributed later (code 400 was, in
  April 2026). Re-check the register before a release.
- **Email.** Addresses use `example.com` (RFC 2606).

## Calibration

**`calibration.reproduction.exposure = 0.22`** (bundled US value 0.3).

**Target.** INE does not publish completed cohort fertility ("descendencia
final"), so it was derived from INE IDB table **1406** (fertility rates by
single year of age, 1975-2024, last updated 2025-11-19). The rate for age *a*
in year *t* is split equally between cohorts *t−a* and *t−a−1*.

- **Validation.** Period sums reproduce INE's published ICF (table 1407) to
  within 0.01. Cohort 1969 gives 1.495, against 1.49 in Esteve, Devolder &
  Domingo, *Perspectives Demogràfiques* 1, CED, 2016.
- **Complete cohorts** (children per woman):

  | Cohort | Value | Cohort | Value |
  |---|---|---|---|
  | 1966 | 1.576 | 1971 | 1.451 |
  | 1967 | 1.562 | 1972 | 1.425 |
  | 1968 | 1.530 | 1973 | 1.401 |
  | 1969 | 1.495 | 1974 | 1.384 |
  | 1970 | 1.476 | 1975 | 1.372 |

- **Incomplete cohorts** (lower bounds): 1976-1980 1.36-1.37.

For context, the period ICF was 1.10 in 2024.

**Measurement.** 150 women aged 46-60 per run, with the `es` pack, reference
date 2026-01-01 (cohorts 1966-1980), counting the `number_of_children`
attribute:

| Exposure | Seed | Births per woman | Childless |
|---|---|---|---|
| 0.30 (US) | 20261018 | 1.77 | 21% |
| 0.20 | 20261018 | 1.37 | 28% |
| 0.22 | 20261018 | 1.46 | 21% |
| 0.22 | 7 | 1.36 | 29% |

The two seeds at 0.22 average 1.41, inside the 1.36-1.58 range of the
target cohorts. With 150 women, the sampling noise is about ±0.1.
