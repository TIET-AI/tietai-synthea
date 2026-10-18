# Synthetic genomics and oncology pack (GO-61)

Everything in this pack is **synthetic test data**. It exists so the platform's genomics and oncology
features (FHIR profile validation, VCF intake, HL7 ORU mapping, report extraction, the oncology case
summary, OMOP export, clinical validation) have deterministic, reviewable fixtures. It contains no real
patient, name, date or identifier; names are generated from Synthea name lists and dates come from the simulation
clock (moved forward by whole years so every diagnosis falls in the TNM 8 era; see Implementation notes). It is not clinical evidence.

Design: `docs/plans/2026-10-17-genomics-oncology/ws5-safety/GO-61-synthetic-data-and-gate-suites.md` (parent
repository). Safety class B.

## Generating

```bash
# the reference pack (also what is committed under examples/genomics-oncology-pack/)
uv run synthea --population 200 --seed 20261017 --age 55-85 --reference-date 20261001 \
    --genomics-cohort --regenerate-reference \
    -c examples/genomics-oncology-pack-recipe.properties --output-dir ./out
diff -r out/genomics-oncology-pack examples/genomics-oncology-pack      # only case/ and *.tbi differ (see below)

# any other population: stock modules, whatever cancers happen to occur
uv run synthea --population 200 --seed 7 --genomics --output-dir ./out
```

* `--genomics` sets `exporter.genomics.export=true` (default **false**). `--genomics-cohort` implies it.
* `--reference-date` is required for reproducibility: the default reference date is the wall clock.
* The reference recipe disables the full per-patient FHIR export (`exporter.fhir.export=false`), which
  dominates run time; the pack builds its own bundles. Pop 200 runs in about 20 s on a laptop.
* The pack is written in two phases so it is identical at any thread count: each person only *stages* a
  small descriptor, and the pack is written once the population is complete, ordered by person uuid.
  Errors of the pack writer (including the PHI scan) stop the run; they are not swallowed by the
  per-exporter error handling.

### Cohort enrichment (`--genomics-cohort`) and the EncounterEnd defect

Stock modules give few cancer cases per 200 persons, mostly breast and prostate. Until 1.5.0 **no lung or
colorectal case ever completed**, because the engine's `EncounterEnd` state never let a module move on
([#119](https://github.com/TIET-AI/tietai-synthea/issues/119)). GO-61 worked around it with an opt-in switch;
1.5.0 fixes it for every run (#120), so the switch no longer exists. One opt-in change remains to make a
four-family pack dense enough:

* `generate.module_patches` = `resources/genomics/cohort_patches.yaml` (set by `--genomics-cohort`): replaces the
  *incidence gate* state of the four cancer modules with a fixed onset probability. Nothing after the gate
  changes. The pack manifest records the hash of the patch file.

## Layout

```
MANIFEST.json                           schema tietai.genomics-pack/v1: seed, module and table sha256s,
                                        per-file sha256, counts, tbi_source "ci", cohort patch hash
patients/<person-uuid>/
  fhir/report-<case>.bundle.json        tietai-genomic-report transaction bundle (GO-10 shape)
  fhir/oncology-<case>.bundle.json      mCODE: tietai-cancer-condition, TNM, markers, treatments (GO-21 shape)
  vcf/SYNTH_<CASE>.vcf.gz (+ .sha256)   VCF 4.3, BGZF, GRCh38 (contigs without chr prefix)
  reports/informe-genetico-<case>.pdf|.txt|.entities.json   Spanish genetic report (C5 tietai.genomic-extraction/v1)
  reports/informe-ap-<case>.pdf|.txt|.entities.json         Spanish synoptic pathology (C5 tietai.synoptic-pathology/v1)
  case/oncology-case-<case>.golden.json C4 golden, written by the Hydra GO-20 procedure (not by this generator)
negatives/<nn>-<invariant>-<slug>/{bundle.json,expected.json}     the 16 negative fixtures
known-gaps/01-.../{bundle.json,expected.json}                      the structural ALK fusion (see below)
oru/<case>.hl7                          HL7 v2 ORU^R01 in the GO-12 fixture format
```

`.tbi` indexes are produced by `tabix` in CI (`.github/workflows/genomics-pack.yml`) and committed next to the
reference `.vcf.gz`; the generator never writes them (`tbi_source: "ci"`).

### Staging, dates and case links

* **Staging** is assigned by the generator (`export/genomics_staging.py`), not taken from the modules, whose T/N/M and
  stage numerals can contradict each other. Each case gets a hand-checked **TNM 8th edition** combination per site
  (breast, lung, colon: anatomic stage group; prostate: pathological prognostic group from pT, PSA and Grade Group);
  tumour size follows pT where T is size-defined, positive nodes follow pN. The module's stage numeral only chooses
  among the combinations. `tests/test_genomics_staging.py` checks size/T/N/stage consistency of every case against
  independently written rules. Tables are pending pathologist review.
* **Dates.** TNM 8 applies from 2018-01-01 and the reports cite ClinVar 2026-09-01, so each case's dates are moved
  forward by whole years until the diagnosis is in 2018 or later, and the genetic report is issued after the release.
* **Case link.** The case's `Condition` is written with `PUT Condition/<id>` (client id) in **both** bundles of the case
  and every other resource points at it as `Condition/<id>` (`Observation.focus` for TNM, markers, variants and msi;
  `reasonReference` for treatments). GO-20 attributes results to a case only by such an explicit reference, which is
  what makes second cases (five patients have two) attributable. Why PUT and a literal reference: the platform has no
  `identifier` search parameter on Condition (conditional create fails) and its bundle processor does not register a
  temporary id for PUT entries. Client ids are unique across organisations (a second tenant loading the same pack gets
  409 "resource id already in use").

### Bundle shapes

Report bundles contain, in this order (every reference points to an earlier entry): lab `Organization`, `Patient`
(conditional create on the synthetic identifier), tumour `Specimen` (and a blood `Specimen` when a germline
variant is present), a `tietai-genomic-document` `DocumentReference` for the PDF (`drs://synthetic.tiet.ai/...`,
sha-256 and size of the real PDF), `tietai-variant` Observations (eight LOINC components, laboratory + GE
categories, HGVS as `http://varnomen.hgvs.org` codings, **no** 53037-8), `tietai-diagnostic-implication`
(53037-8 from the curated classification plus `classification-source`; one variant of each family has two with
different significance for the GO-40 conflict rule) and `tietai-therapeutic-implication` Observations, a colorectal
`msi` Observation, the `tietai-genomic-report` and its `Provenance`. Germline variants **and their implications**
carry `meta.security` `GERMLINE` (`https://tiet.ai/fhir/security`).

Every bundle was validated in enforce mode against the real validator (see the PR for the verification record).

### Known gaps found while building the pack

* **Structural variants.** The spec asks for the ALK fusion as a `tietai-variant` with SO consequence and no HGVS
  component. The platform's `INV-HGVS-1` requires at least one HGVS component, so that form is rejected today.
  The fusion is therefore not in the positive report bundle; it is in the report text, the entity files and the
  `known-gaps/` bundle with the validator's actual answer (`INV-HGVS-1`). Needs a GO-10 decision.
* **msi/tmb results** are accepted but make the report "not tagged validated" (`INV-RESULT-1-UNRESOLVED` warning),
  a documented GO-10 limit.
* Negative `14-GO-05-LABEL-ON-WRITE` (germline variant without the label) is accepted by `$validate`: GERMLINE is
  applied by GO-05 at write time. Negative `16-STAGE_WITHOUT_CATEGORIES` is accepted by `$validate`; Hydra's
  `validate_tnm` flags it (`layer: hydra-tool`).

## Curated tables (pending review)

* `resources/genomics/curated_variants.yaml` (+ schema): 10 entries. Review status **pending clinical geneticist
  sign-off**. Values were cross-checked on 2026-10-18 against VariantValidator (GRCh38), HGNC and NCBI ClinVar.
  Deviation from the spec text: BRCA1 is `c.5266dup` (current HGVS), not `c.5266dupC`.
* `resources/genomics/cancer_codes.yaml`: SNOMED / ICD-O-3 / CIE-10-ES triplets, marker LOINC mapping
  (85337-4, 85339-0, 85319-2 to 16112-5, 16113-3, 48676-1) and RxNorm to ATC (L01/L02). **Pending terminology
  owner review.**
* The generator refuses to start when an HGVS string fails the syntax check, when a germline entry has no GERMLINE
  mapping, or when the curated table differs from the one recorded in the committed reference pack (unless
  `--regenerate-reference`).
* `resources/genomics/c5/*.schema.json` are copies of the C5 schemas from the Hydra repository
  (`origin/feat/GO-22`, which contains GO-13's `genomic_v1.yaml`; PRs #1399 and #1401, in review). Re-sync after
  they merge.

## PHI policy

The generator scans every text artefact (JSON, text twins, HL7, sidecars, the decompressed VCF) with the Spanish
identifier patterns of HG-20 REQ-07 (DNI/NIE, NHC, CIP/TSI, NASS, phone, postal code in context, e-mail) and aborts
naming the file and the pattern, never the match. Bare 9- and 12-digit runs count only in context, because
SNOMED and NCBI codes have that shape. UUIDs, hashes and object ids are removed before scanning.

## Consumers

| Consumer | Uses |
|---|---|
| fhir-service (GO-61 part c) | `scripts/sync-genomics-fixtures.sh <pack>`: `patients/*/fhir/*.bundle.json`, `negatives/`, `known-gaps/`, `MANIFEST.json`, VCFs |
| Hydra gate suites | `reports/*.txt` + `*.entities.json`, `case/*.golden.json`, bundles, `oru/` |
| GO-41 fhir2omop | oncology bundles |
| GO-13 / GO-22 dev runs | the PDFs and `.txt` twins |
