# Synthea Python - Resources Documentation

This document details all the resources included in the Synthea Python implementation, copied from the original Java project.

## Resource Summary

- **Total Size**: 75 MB
- **Total Files**: 425 files
- **Disease Modules**: 241 JSON files

## Directory Structure

```
resources/
├── modules/           # 241 disease module JSON files
├── providers/         # Healthcare provider data
├── payers/           # Insurance payer data  
├── costs/            # Healthcare cost data
├── geography/        # Geographic and demographic data
├── covid19/          # COVID-19 specific modules
├── export/           # Export templates and mappings
├── keep_modules/     # Priority modules configuration
├── lookup_tables/    # Transition probability tables
└── [root files]      # Configuration and reference data
```

## Detailed Contents

### 1. Disease Modules (`modules/`)
**241 JSON module files** implementing disease progressions:

#### Major Categories:
- **Allergies**: allergic_rhinitis.json, allergies.json, food_allergies.json
- **Cancer**: breast_cancer/, colorectal_cancer.json, lung_cancer.json
- **Cardiovascular**: atrial_fibrillation.json, heart_disease.json, hypertension.json, stroke.json
- **Respiratory**: asthma.json, bronchitis.json, copd.json, pneumonia.json
- **Metabolic**: diabetes.json, prediabetes.json, metabolic_syndrome_disease.json
- **Mental Health**: anxiety.json, depression.json, dementia.json
- **Infectious**: ear_infections.json, urinary_tract_infections.json, sinusitis.json
- **COVID-19**: covid19/ directory with vaccination and treatment modules
- **Pediatric**: wellness_encounters.json, immunizations.json
- **Women's Health**: pregnancy.json, contraceptive_maintenance.json
- **Chronic Conditions**: chronic_kidney_disease.json, lupus.json, rheumatoid_arthritis.json

#### Subdirectories:
- `allergies/`: Detailed allergy modules
- `anemia/`: Anemia-related conditions
- `breast_cancer/`: Breast cancer progression modules
- `cardio/`: Cardiovascular disease modules
- `conjunctivitis/`: Eye infection modules
- `contraceptives/`: Birth control modules
- `covid19/`: COVID-19 and vaccination modules
- `dermatitis/`: Skin condition modules
- `dialysis/`: Kidney dialysis modules
- `ear_infections/`: Otitis media modules
- `injuries/`: Injury and trauma modules
- `medications/`: Medication-specific modules
- `metabolic_syndrome/`: Metabolic disorder modules
- `osteoporosis/`: Bone health modules
- `pregnancy/`: Pregnancy and childbirth modules
- `weight_loss/`: Weight management modules

### 2. Provider Data (`providers/`)
**15 CSV files** with healthcare facility data:
- `hospitals.csv` - Hospital facilities
- `primary_care_facilities.csv` - Primary care clinics
- `urgent_care_facilities.csv` - Urgent care centers
- `nursing.csv` - Nursing homes
- `hospice.csv` - Hospice facilities
- `dialysis.csv` - Dialysis centers
- `home_health_agencies.csv` - Home health providers
- `ambulatory_surgical_center.csv` - Surgical centers
- `va_facilities.csv` - Veterans Affairs facilities
- `ihs_facilities.csv` - Indian Health Service facilities
- `rehab.csv` - Rehabilitation centers
- `longterm.csv` - Long-term care facilities

### 3. Payer Data (`payers/`)
**4 CSV files** with insurance information:
- `insurance_companies.csv` - Private insurers
- `insurance_eligibilities.csv` - Eligibility criteria
- `carriers.csv` - Medicare carriers
- `payers.csv` - All payer information

### 4. Cost Data (`costs/`)
**14 CSV files** with healthcare pricing:
- `encounters.csv` - Visit costs
- `medications.csv` - Drug prices
- `procedures.csv` - Procedure costs
- `immunizations.csv` - Vaccine costs
- `labs.csv` - Laboratory test costs
- `devices.csv` - Medical device costs
- `supplies.csv` - Medical supply costs
- `*_adjustments.csv` - Regional cost adjustments

### 5. Geographic Data (`geography/`)
**7 files** with location and demographic data:
- `demographics.csv` - Population demographics
- `fipscodes.csv` - FIPS geographic codes
- `foreign_birthplace.json` - Immigration data
- `timezones.csv` - Time zone mappings
- `zipcodes.csv` - ZIP code data
- `ma_geography.json` - Massachusetts specific data
- `sdoh.csv` - Social determinants of health

### 6. Clinical Reference Data (root)
- `cdc_growth_charts.json` (537 KB) - Pediatric growth standards
- `immunization_schedule.json` - Vaccine schedules
- `birthweights.csv` - Birth weight distributions
- `bmi_correlations.json` - BMI correlation data
- `gbd_disability_weights.csv` - Disability weights
- `htn_drugs.csv` - Hypertension medications
- `language_lookup.json` - Language distributions
- `biometrics.yml` - Biometric data configurations

### 7. COVID-19 Resources (`covid19/`)
- `supplies_mapping.json` - PPE and supply mappings
- COVID-19 specific module configurations

### 8. Export Templates (`export/`)
- FHIR mapping files
- CCDA templates
- Custom report templates
- Symptoms and condition mappings

### 9. Configuration Files
- `synthea.properties` - Main configuration
- `log4j.xml` - Logging configuration
- `names.yml` - Name generation data
- `growth_data_error_rates.json` - Error modeling

## Usage

All resources are automatically loaded when using the Synthea Python CLI or API:

```python
from synthea.engine.module import Module

# Modules are loaded from resources/modules/
Module.load_modules('resources/modules')
modules = Module.get_all_modules()
print(f"Loaded {len(modules)} disease modules")  # Output: Loaded 241 disease modules
```

```bash
# CLI automatically uses all resources
uv run synthea -p 100

# List all available modules
uv run synthea --list-modules
```

## Resource Validation

Run the resource test script to verify all resources are properly loaded:

```bash
cd synthea-python
source .venv/bin/activate
python test_resources.py
```

Expected output:
- ✓ Loaded 241 disease modules
- ✓ Total resource files: 425
- ✓ Resource directories: 11

## Notes

- All resources are identical to the original Java Synthea project
- Resources are loaded lazily for better performance
- Module loading supports both JSON files and subdirectories
- CSV files use standard formats compatible with pandas
- All costs are in USD and can be adjusted regionally