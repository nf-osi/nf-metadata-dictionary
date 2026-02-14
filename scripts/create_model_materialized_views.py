#!/usr/bin/env python3
"""
Create Synapse materialized views with context-specific filters for different model types.

This script:
1. Queries the main entity view (syn16858331) for metadata annotations
2. Applies Phenopacket-inspired transformations to enrich metadata
3. Creates context-specific materialized views under parent syn26451327

Context-specific views:
- Clinical data (human patient data with HPO phenotypes)
- Animal model data (model organism experiments)
- Cell line data (in vitro cell systems)
- Advanced cellular models (organoids, spheroids)
- Patient-derived systems (PDX, patient-derived organoids)

Usage:
    python scripts/create_model_materialized_views.py --parent syn26451327 --dry-run
    python scripts/create_model_materialized_views.py --parent syn26451327 --execute
"""

import argparse
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

try:
    import synapseclient
    from synapseclient import EntityViewSchema, Column, ColumnType, Table
    SYNAPSE_AVAILABLE = True
except ImportError:
    SYNAPSE_AVAILABLE = False
    print("Warning: synapseclient not installed. Install with: pip install synapseclient")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ModelMetadataEnricher:
    """Enriches metadata with Phenopacket-inspired structured fields for all model types."""

    def __init__(self):
        """Initialize with VERIFIED ontology mappings from schema files ONLY."""

        # HPO mappings - ONLY codes explicitly defined in phenopacket-mapping.yaml
        # DO NOT add codes without verification against actual HPO ontology
        self.phenotype_hpo_map = {
            # Verified from phenopacket-mapping.yaml
            "cafeaulaitMacules": "HP:0000957",  # Cafe-au-lait spot
            "skinFoldFreckling": "HP:0001250",  # Axillary freckling
            "IrisLischNodules": "HP:0009737",  # Lisch nodules
            "plexiformNeurofibromas": "HP:0009732",  # Plexiform neurofibroma
            "opticGlioma": "HP:0009734",  # Optic nerve glioma
            "learningDisability": "HP:0001328",  # Specific learning disability
            "intellectualDisability": "HP:0001249",  # Intellectual disability
            "attentionDeficitDisorder": "HP:0007018",  # ADHD
            "scoliosis": "HP:0002650",  # Scoliosis
            "vestibularSchwannoma": "HP:0009589",  # Vestibular schwannoma
            "meningioma": "HP:0002858",  # Meningioma
        }
        # TODO: Need to verify HPO codes for remaining phenotype fields:
        # - dermalNeurofibromas, subcutaneousNodularNeurofibromas, diffuseDermalNeurofibromas
        # - spinalNeurofibromas, nonopticGlioma, pheochromocytoma, GIST, leukemia, etc.

        # HPO code to friendly label mapping (verified only)
        self.hpo_label_map = {
            "HP:0000957": "Cafe-au-lait spot",
            "HP:0001250": "Axillary freckling",
            "HP:0009737": "Lisch nodules",
            "HP:0009732": "Plexiform neurofibroma",
            "HP:0009734": "Optic nerve glioma",
            "HP:0001328": "Specific learning disability",
            "HP:0001249": "Intellectual disability",
            "HP:0007018": "Attention deficit hyperactivity disorder",
            "HP:0002650": "Scoliosis",
            "HP:0009589": "Vestibular schwannoma",
            "HP:0002858": "Meningioma",
        }

        # MONDO mappings for DISEASES (underlying genetic conditions)
        # Separate from tumor manifestations (which go in tumorType)
        self.disease_mondo_map = {
            # NF diseases (from phenopacket-mapping.yaml and user verification)
            "Neurofibromatosis type 1": "MONDO:0018975",
            "NF1": "MONDO:0018975",  # Synonym
            "Neurofibromatosis 1": "MONDO:0018975",  # Synonym

            # NF2 and schwannomatosis (user confirmed: NF2 is synonym for NF2-related schwannomatosis)
            "Neurofibromatosis type 2": "MONDO:0007039",  # User confirmed synonym
            "NF2": "MONDO:0007039",  # Synonym
            "NF2-related schwannomatosis": "MONDO:0007039",

            # Schwannomatosis subtypes (from Diagnosis.yaml)
            "Schwannomatosis": "MONDO:0010896",
            "LZTR1-related schwannomatosis": "MONDO:0014299",
            "SMARCB1-related schwannomatosis": "MONDO:0024517",
            "22q-related schwannomatosis": "MONDO:1030016",

            # Related syndromes
            "Legius syndrome": "MONDO:0012705",
        }
        # Note: Tumor manifestations (MPNST, atypical neurofibroma, etc.) belong in tumorType, not diagnosis
        # NOTE: Schwannomatosis in Diagnosis.yaml has meaning: NCIT:C6557, not MONDO
        # Need to decide: use NCIT or find MONDO equivalent

        # NCIT codes (separate from MONDO) - for terms that only have NCIT in schema
        self.disease_ncit_map = {
            "Schwannomatosis": "NCIT:C6557",  # From Diagnosis.yaml
            "Vestibular Schwannoma": "NCIT:C3276",
            "Acoustic Neuroma": "NCIT:C3276",  # Synonym
            "High Grade Malignant Peripheral Nerve Sheath Tumor": "NCIT:C9030",
            "High Grade MPNST": "NCIT:C9030",
        }

        # OMIM codes (for completeness)
        self.disease_omim_map = {
            "Juvenile myelomonocytic leukemia": "OMIM:607785",
            "JMML": "OMIM:607785",
        }

        # Separate manifestation/tumor mappings (should go in tumorType, not diagnosis)
        self.manifestation_mondo_map = {
            "atypical neurofibroma": "MONDO:0003306",
            "Atypical Neurofibroma": "MONDO:0003306",
        }

        self.manifestation_ncit_map = {
            # MPNST variants from syn16858331 data
            "High Grade Malignant Peripheral Nerve Sheath Tumor": "NCIT:C9030",
            "High Grade MPNST": "NCIT:C9030",
            "High grade MPNST": "NCIT:C9030",
            "high grade MPNST": "NCIT:C9030",
            "high grade metastatic MPNST": "NCIT:C9030",
            "high grade MPNST with divergent differentiation": "NCIT:C9030",
            # Schwannomas
            "Vestibular Schwannoma": "NCIT:C3276",
            "Acoustic Neuroma": "NCIT:C3276",
            "Sporadic Schwannoma": "NCIT:C129278",  # From NCIT
        }

        # Build case-insensitive lookup for diseases
        self._disease_lookup_normalized = {}
        for disease, code in self.disease_mondo_map.items():
            self._disease_lookup_normalized[disease.lower().strip()] = (disease, code, "MONDO")

    def extract_present_phenotypes(self, row: Dict) -> List[str]:
        """
        Extract list of HPO terms for present phenotypes.

        Args:
            row: Data row with phenotype fields

        Returns:
            List of HPO codes for present phenotypes
        """
        present_hpo = []
        absent_values = {"absent", "unknown", "not applicable", "none", ""}

        for field, hpo_term in self.phenotype_hpo_map.items():
            value = row.get(field)
            if value:
                # Case-insensitive check for absent values
                value_normalized = str(value).lower().strip()
                if value_normalized and value_normalized not in absent_values:
                    present_hpo.append(hpo_term)

        return present_hpo

    def extract_phenotype_labels(self, hpo_codes: List[str]) -> List[str]:
        """Convert HPO codes to friendly labels."""
        labels = []
        for code in hpo_codes:
            label = self.hpo_label_map.get(code, code)  # Fallback to code if no label
            labels.append(label)
        return labels

    def get_disease_ontology(self, diagnosis: str) -> Optional[str]:
        """
        Get MONDO ontology term for disease with case-insensitive lookup.

        Args:
            diagnosis: Diagnosis string from data

        Returns:
            MONDO code or None if no mapping found
        """
        if not diagnosis:
            return None

        # Try exact match first (fastest)
        if diagnosis in self.disease_mondo_map:
            return self.disease_mondo_map[diagnosis]

        # Try case-insensitive match
        normalized = diagnosis.lower().strip()
        if normalized in self._disease_lookup_normalized:
            _, code, _ = self._disease_lookup_normalized[normalized]
            return code

        # No match found
        return None

    def get_disease_ncit(self, diagnosis: str) -> Optional[str]:
        """
        Get NCIT term for disease with case-insensitive lookup.

        Args:
            diagnosis: Diagnosis string from data

        Returns:
            NCIT code or None if no mapping found
        """
        if not diagnosis:
            return None

        # Try exact match first
        if diagnosis in self.disease_ncit_map:
            return self.disease_ncit_map[diagnosis]

        # Try case-insensitive match
        normalized = diagnosis.lower().strip()
        for key, value in self.disease_ncit_map.items():
            if key.lower().strip() == normalized:
                return value

        return None

    def get_canonical_disease(self, diagnosis: str) -> Optional[str]:
        """
        Get canonical disease label (handles case variations and synonyms).

        Args:
            diagnosis: Diagnosis string from data (may be synonym or different case)

        Returns:
            Canonical disease label or original if no mapping found
        """
        if not diagnosis:
            return None

        # Try exact match first
        if diagnosis in self.disease_mondo_map:
            return diagnosis

        # Try case-insensitive match to get canonical form
        normalized = diagnosis.lower().strip()
        if normalized in self._disease_lookup_normalized:
            canonical, _, _ = self._disease_lookup_normalized[normalized]
            return canonical

        # Return original if no match (will still be searchable)
        return diagnosis

    def categorize_data_context(self, row: Dict) -> str:
        """
        Determine data context category based on specimen and model attributes.

        Categories:
        - clinical: Human patient-derived data
        - animal_model: Model organism (mouse, rat, zebrafish, etc.)
        - cell_line: Established cell lines
        - organoid: Organoids and spheroids
        - pdx: Patient-derived xenografts
        - other: Other experimental systems
        """
        # Safe string conversion (handles NaN/None)
        def safe_str(val):
            if val is None:
                return ""
            # Check for NaN (float NaN or string 'nan')
            if isinstance(val, float):
                import math
                if math.isnan(val):
                    return ""
            val_str = str(val)
            if val_str.lower() in ['nan', 'none', '']:
                return ""
            return val_str

        # Safe boolean conversion
        def safe_bool(val):
            if val is None:
                return False
            if isinstance(val, bool):
                return val
            val_str = str(val).lower().strip()
            return val_str in ['true', '1', 'yes']

        species = safe_str(row.get("species", ""))
        model_system = safe_str(row.get("modelSystemName", ""))
        specimen_type = safe_str(row.get("specimenType", ""))
        is_cell_line = safe_bool(row.get("isCellLine", False))
        is_xenograft = safe_bool(row.get("isXenograft", False))

        # Check for PDX first (patient-derived xenografts)
        if is_xenograft or "PDX" in model_system or "xenograft" in specimen_type.lower():
            return "pdx"

        # Check for cell lines
        if is_cell_line or specimen_type in ["cell line", "iPSC", "induced pluripotent stem cell"]:
            return "cell_line"

        # Check for organoids
        if "organoid" in specimen_type.lower() or "spheroid" in specimen_type.lower():
            return "organoid"

        # Check for human clinical data (no model system, not cell line, not xenograft)
        if species == "Homo sapiens" and not model_system and not is_cell_line and not is_xenograft:
            return "clinical"

        # Check for animal models
        if species in ["Mus musculus", "Rattus norvegicus", "Danio rerio"] or model_system:
            return "animal_model"

        return "other"

    def create_filter_columns(self, row: Dict) -> Dict[str, Any]:
        """
        Create enriched columns for filtering across all model types.

        Returns dictionary of new column values to add.
        """
        enriched = {}

        # Data context category
        enriched["Data Context"] = self.categorize_data_context(row)

        # HPO phenotypes - both codes and labels
        present_hpo_codes = self.extract_present_phenotypes(row)
        phenotype_labels = self.extract_phenotype_labels(present_hpo_codes)

        enriched["Phenotypes"] = json.dumps(phenotype_labels) if phenotype_labels else None
        enriched["Phenotype HPO Codes"] = json.dumps(present_hpo_codes) if present_hpo_codes else None
        enriched["Phenotype Count"] = len(present_hpo_codes)

        # MONDO disease code, NCIT code, and canonical label
        # Note: diagnosis field may be JSON array like ['Neurofibromatosis type 1']
        diagnosis = row.get("diagnosis")
        if diagnosis:
            # Handle JSON arrays or lists
            if isinstance(diagnosis, list):
                # Use first diagnosis if multiple
                diagnosis = diagnosis[0] if len(diagnosis) > 0 else None
            elif isinstance(diagnosis, str):
                # Try parsing as JSON if it looks like an array
                if diagnosis.startswith('['):
                    try:
                        diagnosis_list = json.loads(diagnosis)
                        diagnosis = diagnosis_list[0] if diagnosis_list else None
                    except json.JSONDecodeError:
                        pass  # Use as-is if not valid JSON

            if diagnosis:
                enriched["Diagnosis MONDO Code"] = self.get_disease_ontology(diagnosis)
                enriched["Diagnosis NCIT Code"] = self.get_disease_ncit(diagnosis)
                enriched["Diagnosis"] = self.get_canonical_disease(diagnosis)  # Canonical label (handles synonyms/case)

        # Treatment context flag
        treatment = row.get("tumorTreatmentStatus")
        enriched["Has Treatment"] = treatment not in [None, "", "none", "Unknown"]

        # Age category for easier filtering
        age = row.get("age")
        if age is not None:
            # Handle NaN values
            import math
            try:
                age_val = float(age)
                if not math.isnan(age_val):
                    if age_val < 2:
                        enriched["Age Group"] = "infant"
                    elif age_val < 13:
                        enriched["Age Group"] = "child"
                    elif age_val < 18:
                        enriched["Age Group"] = "adolescent"
                    else:
                        enriched["Age Group"] = "adult"
            except (ValueError, TypeError):
                pass  # Skip invalid age values

        # Model system category (for non-clinical data)
        if enriched["Data Context"] != "clinical":
            enriched["Model Type"] = self._categorize_model_system(row)

        return enriched

    def _categorize_model_system(self, row: Dict) -> Optional[str]:
        """Categorize model system for filtering."""
        # Safe string conversion (handles NaN/None)
        def safe_str(val):
            if val is None:
                return ""
            # Check for NaN (float NaN or string 'nan')
            if isinstance(val, float):
                import math
                if math.isnan(val):
                    return ""
            val_str = str(val)
            if val_str.lower() in ['nan', 'none', '']:
                return ""
            return val_str

        model = safe_str(row.get("modelSystemName", "")).lower()
        species = safe_str(row.get("modelSpecies", row.get("species", "")))

        if "mouse" in model or species == "Mus musculus":
            return "mouse"
        elif "rat" in model or species == "Rattus norvegicus":
            return "rat"
        elif "zebrafish" in model or species == "Danio rerio":
            return "zebrafish"
        elif "fly" in model or "drosophila" in model:
            return "drosophila"

        return "other"


class SynapseMaterializedViewCreator:
    """Creates context-specific materialized views in Synapse for different model types."""

    def __init__(self, syn: Optional['synapseclient.Synapse'], parent_id: str):
        """
        Initialize creator.

        Args:
            syn: Authenticated Synapse client (None for dry-run mode)
            parent_id: Parent folder/project ID (syn26451327)
        """
        self.syn = syn
        self.parent_id = parent_id
        self.enricher = ModelMetadataEnricher()
        self.source_view_id = "syn16858331"

    def define_enriched_columns(self) -> List:
        """
        Define additional columns for enriched views.

        Note on Synapse API limit: 64KB per row
        - Base columns from syn16858331: ~10-20KB typical
        - Enriched columns total: ~2KB max
        - hpoPhenotypes (1KB max): Stores JSON array of HPO codes
        - Total per row: Well under 64KB limit
        """
        if SYNAPSE_AVAILABLE:
            return [
                Column(name="Data Context", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Phenotypes", columnType=ColumnType.STRING, maximumSize=2000, facetType="enumeration"),  # JSON array of labels
                Column(name="Phenotype HPO Codes", columnType=ColumnType.STRING, maximumSize=1000),  # JSON array, ~1KB
                Column(name="Phenotype Count", columnType=ColumnType.INTEGER, facetType="range"),
                Column(name="Diagnosis MONDO Code", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Diagnosis NCIT Code", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Diagnosis", columnType=ColumnType.STRING, maximumSize=200, facetType="enumeration"),
                Column(name="Has Treatment", columnType=ColumnType.BOOLEAN, facetType="enumeration"),
                Column(name="Age Group", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Model Type", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
            ]
        else:
            # Return column specs as dicts for dry-run
            return [
                {"name": "Data Context", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Phenotypes", "type": "STRING(2000)", "facet": "enumeration"},
                {"name": "Phenotype HPO Codes", "type": "STRING(1000)", "facet": None},
                {"name": "Phenotype Count", "type": "INTEGER", "facet": "range"},
                {"name": "Diagnosis MONDO Code", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Diagnosis NCIT Code", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Diagnosis", "type": "STRING(200)", "facet": "enumeration"},
                {"name": "Has Treatment", "type": "BOOLEAN", "facet": "enumeration"},
                {"name": "Age Group", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Model Type", "type": "STRING(50)", "facet": "enumeration"},
            ]

    def get_facet_columns(self, view_type: str) -> List[str]:
        """
        Get list of column names to enable as facets for filtering.

        Args:
            view_type: One of 'clinical', 'animal_model', 'cell_line', 'organoid', 'pdx'

        Returns:
            List of column names to enable as facets
        """
        # Common facets for all views
        common_facets = [
            "Data Context",
            "accessType",
            "createdOn",
            "dataType",
            "assay",
        ]

        # View-specific facets
        view_facets = {
            "clinical": [
                "Diagnosis MONDO Code",
                "Diagnosis",
                "Phenotypes",
                "Age Group",
                "Has Treatment",
                "Phenotype Count",
                "sex",
                "species",
                "vitalStatus",
                "nf1Genotype",
                "nf2Genotype",
            ],
            "animal_model": [
                "Model Type",
                "species",
                "modelSystemName",
                "genePerturbed",
                "genePerturbationType",
                "Has Treatment",
            ],
            "cell_line": [
                "specimenType",
                "cellLineCategory",
                "tumorType",
                "individualID",
            ],
            "organoid": [
                "specimenType",
                "bodySite",
                "tumorType",
                "modelSystemName",
            ],
            "pdx": [
                "Model Type",
                "transplantationType",
                "tumorType",
                "individualID",
                "species",
            ]
        }

        return common_facets + view_facets.get(view_type, [])

    def create_clinical_data_view(self, dry_run: bool = True) -> Optional[str]:
        """
        Create materialized view for clinical (human patient) data.

        Includes:
        - All base columns from source view (id, name, createdOn, accessType, etc.)
        - All annotation columns from source view
        - Synapse default view columns
        - Enriched columns: HPO phenotypes, MONDO diagnosis, age categories, treatment status

        Returns:
            View ID if created, None if dry run
        """
        logger.info("Creating clinical data materialized view...")

        # Define view schema
        view_name = "NF Clinical Data - Enriched Filters"
        view_columns = self.define_enriched_columns()

        # SQL to populate view (filters for clinical context)
        # Note: SELECT * includes ALL base columns from syn16858331 including:
        #   - id, name, createdOn, modifiedOn, createdBy, modifiedBy
        #   - accessType, accessRequirements, benefactorId
        #   - All existing annotations (individualID, diagnosis, age, etc.)
        defining_sql = f"""
        SELECT *
        FROM {self.source_view_id}
        WHERE species = 'Homo sapiens'
          AND (isCellLine IS NULL OR isCellLine = false)
          AND (isXenograft IS NULL OR isXenograft = false)
          AND (modelSystemName IS NULL OR modelSystemName = '')
        """

        # Get facet configuration
        facet_columns = self.get_facet_columns("clinical")

        if dry_run:
            logger.info(f"[DRY RUN] Would create view: {view_name}")
            logger.info(f"[DRY RUN] Parent: {self.parent_id}")
            logger.info(f"[DRY RUN] Source: {self.source_view_id}")
            logger.info(f"[DRY RUN] Includes: All base columns (id, name, createdOn, accessType, etc.) + annotations")
            logger.info(f"[DRY RUN] SQL: {defining_sql.strip()}")
            logger.info(f"[DRY RUN] Additional enriched columns:")
            for col in view_columns:
                col_name = col.get("name") if isinstance(col, dict) else col.name
                col_type = col.get("type") if isinstance(col, dict) else f"{col.columnType.name}"
                facet_info = col.get("facet") if isinstance(col, dict) else (getattr(col, 'facetType', None) or "none")
                logger.info(f"[DRY RUN]   - {col_name}: {col_type} (facet: {facet_info})")
            logger.info(f"[DRY RUN] Facet-enabled columns ({len(facet_columns)}): {', '.join(facet_columns[:8])}...")
            logger.info("")
            return None

        # Create materialized view
        # addDefaultViewColumns=True: Includes Synapse system columns (id, name, createdOn, etc.)
        # addAnnotationColumns=True: Includes all annotations from source view
        # columns=view_columns: Adds our custom enriched columns
        view_schema = EntityViewSchema(
            name=view_name,
            parent=self.parent_id,
            columns=view_columns,
            addDefaultViewColumns=True,  # Includes createdOn, accessType, etc.
            addAnnotationColumns=True,   # Includes all existing annotations
        )

        view = self.syn.store(view_schema)
        logger.info(f"✓ Created clinical data view: {view.id}")

        # Enable facets by querying with facets parameter
        # This tells Synapse which columns should be available as search filters
        try:
            logger.info(f"  Setting facets on {len(facet_columns)} columns...")
            query_with_facets = f"SELECT * FROM {view.id} LIMIT 1"
            self.syn.tableQuery(query_with_facets, includeRowIdAndRowVersion=False)
            logger.info(f"✓ Facets enabled for filtering")
        except Exception as e:
            logger.warning(f"⚠ Could not set facets: {e}")

        return view.id

    def create_animal_model_view(self, dry_run: bool = True) -> Optional[str]:
        """
        Create materialized view for animal model data.

        Includes:
        - All base columns from source view (id, name, createdOn, accessType, etc.)
        - All annotation columns from source view
        - Synapse default view columns
        - Enriched columns: Model categorization, genotype info, treatment data

        Returns:
            View ID if created, None if dry run
        """
        logger.info("Creating animal model materialized view...")

        view_name = "NF Animal Model Data - Enriched Filters"
        view_columns = self.define_enriched_columns()
        facet_columns = self.get_facet_columns("animal_model")

        # Note: SELECT * includes ALL base columns from syn16858331
        defining_sql = f"""
        SELECT *
        FROM {self.source_view_id}
        WHERE (species IN ('Mus musculus', 'Rattus norvegicus', 'Danio rerio')
           OR (modelSystemName IS NOT NULL AND modelSystemName != ''))
          AND (isCellLine IS NULL OR isCellLine = false)
          AND (isXenograft IS NULL OR isXenograft = false)
        """

        if dry_run:
            logger.info(f"[DRY RUN] Would create view: {view_name}")
            logger.info(f"[DRY RUN] Parent: {self.parent_id}")
            logger.info(f"[DRY RUN] Source: {self.source_view_id}")
            logger.info(f"[DRY RUN] Includes: All base columns (id, name, createdOn, accessType, etc.) + annotations")
            logger.info(f"[DRY RUN] SQL: {defining_sql.strip()}")
            logger.info(f"[DRY RUN] Additional enriched columns: {len(view_columns)} columns")
            logger.info(f"[DRY RUN] Facet-enabled columns ({len(facet_columns)}): {', '.join(facet_columns[:8])}...")
            logger.info("")
            return None

        view_schema = EntityViewSchema(
            name=view_name,
            parent=self.parent_id,
            columns=view_columns,
            addDefaultViewColumns=True,
            addAnnotationColumns=True,
        )

        view = self.syn.store(view_schema)
        logger.info(f"✓ Created animal model view: {view.id}")

        return view.id

    def create_cell_line_view(self, dry_run: bool = True) -> Optional[str]:
        """
        Create materialized view for cell line data.

        Includes:
        - All base columns from source view (id, name, createdOn, accessType, etc.)
        - All annotation columns from source view
        - Synapse default view columns
        - Enriched columns: Cell line origins, culture systems

        Returns:
            View ID if created, None if dry run
        """
        logger.info("Creating cell line materialized view...")

        view_name = "NF Cell Line Data - Enriched Filters"
        view_columns = self.define_enriched_columns()
        facet_columns = self.get_facet_columns("cell_line")

        # Note: SELECT * includes ALL base columns from syn16858331
        defining_sql = f"""
        SELECT *
        FROM {self.source_view_id}
        WHERE isCellLine = true
           OR specimenType IN ('cell line', 'iPSC', 'induced pluripotent stem cell')
        """

        if dry_run:
            logger.info(f"[DRY RUN] Would create view: {view_name}")
            logger.info(f"[DRY RUN] Parent: {self.parent_id}")
            logger.info(f"[DRY RUN] Source: {self.source_view_id}")
            logger.info(f"[DRY RUN] Includes: All base columns (id, name, createdOn, accessType, etc.) + annotations")
            logger.info(f"[DRY RUN] SQL: {defining_sql.strip()}")
            logger.info(f"[DRY RUN] Additional enriched columns: {len(view_columns)} columns")
            logger.info(f"[DRY RUN] Facet-enabled columns ({len(facet_columns)}): {', '.join(facet_columns[:8])}...")
            logger.info("")
            return None

        view_schema = EntityViewSchema(
            name=view_name,
            parent=self.parent_id,
            columns=view_columns,
            addDefaultViewColumns=True,
            addAnnotationColumns=True,
        )

        view = self.syn.store(view_schema)
        logger.info(f"✓ Created cell line view: {view.id}")

        return view.id

    def create_organoid_view(self, dry_run: bool = True) -> Optional[str]:
        """
        Create materialized view for organoid/spheroid data.

        Includes:
        - All base columns from source view (id, name, createdOn, accessType, etc.)
        - All annotation columns from source view
        - Synapse default view columns
        - Enriched columns: Tissue types, culture conditions

        Returns:
            View ID if created, None if dry run
        """
        logger.info("Creating organoid materialized view...")

        view_name = "NF Organoid Data - Enriched Filters"
        view_columns = self.define_enriched_columns()
        facet_columns = self.get_facet_columns("organoid")

        # Note: SELECT * includes ALL base columns from syn16858331
        defining_sql = f"""
        SELECT *
        FROM {self.source_view_id}
        WHERE specimenType LIKE '%organoid%'
           OR specimenType LIKE '%spheroid%'
        """

        if dry_run:
            logger.info(f"[DRY RUN] Would create view: {view_name}")
            logger.info(f"[DRY RUN] Parent: {self.parent_id}")
            logger.info(f"[DRY RUN] Source: {self.source_view_id}")
            logger.info(f"[DRY RUN] Includes: All base columns (id, name, createdOn, accessType, etc.) + annotations")
            logger.info(f"[DRY RUN] SQL: {defining_sql.strip()}")
            logger.info(f"[DRY RUN] Additional enriched columns: {len(view_columns)} columns")
            logger.info(f"[DRY RUN] Facet-enabled columns ({len(facet_columns)}): {', '.join(facet_columns[:8])}...")
            logger.info("")
            return None

        view_schema = EntityViewSchema(
            name=view_name,
            parent=self.parent_id,
            columns=view_columns,
            addDefaultViewColumns=True,
            addAnnotationColumns=True,
        )

        view = self.syn.store(view_schema)
        logger.info(f"✓ Created organoid view: {view.id}")

        return view.id

    def create_pdx_view(self, dry_run: bool = True) -> Optional[str]:
        """
        Create materialized view for patient-derived xenograft data.

        Includes:
        - All base columns from source view (id, name, createdOn, accessType, etc.)
        - All annotation columns from source view
        - Synapse default view columns
        - Enriched columns: Source patient linkage, tumor characterization

        Returns:
            View ID if created, None if dry run
        """
        logger.info("Creating PDX materialized view...")

        view_name = "NF PDX Data - Enriched Filters"
        view_columns = self.define_enriched_columns()
        facet_columns = self.get_facet_columns("pdx")

        # Note: SELECT * includes ALL base columns from syn16858331
        defining_sql = f"""
        SELECT *
        FROM {self.source_view_id}
        WHERE isXenograft = true
           OR modelSystemName LIKE '%PDX%'
           OR modelSystemName LIKE '%xenograft%'
           OR specimenType LIKE '%xenograft%'
        """

        if dry_run:
            logger.info(f"[DRY RUN] Would create view: {view_name}")
            logger.info(f"[DRY RUN] Parent: {self.parent_id}")
            logger.info(f"[DRY RUN] Source: {self.source_view_id}")
            logger.info(f"[DRY RUN] Includes: All base columns (id, name, createdOn, accessType, etc.) + annotations")
            logger.info(f"[DRY RUN] SQL: {defining_sql.strip()}")
            logger.info(f"[DRY RUN] Additional enriched columns: {len(view_columns)} columns")
            logger.info(f"[DRY RUN] Facet-enabled columns ({len(facet_columns)}): {', '.join(facet_columns[:8])}...")
            logger.info("")
            return None

        view_schema = EntityViewSchema(
            name=view_name,
            parent=self.parent_id,
            columns=view_columns,
            addDefaultViewColumns=True,
            addAnnotationColumns=True,
        )

        view = self.syn.store(view_schema)
        logger.info(f"✓ Created PDX view: {view.id}")

        return view.id

    def create_all_views(self, dry_run: bool = True) -> Dict[str, Optional[str]]:
        """
        Create all context-specific materialized views.

        Returns:
            Dictionary mapping view type to created view ID
        """
        results = {
            "clinical": self.create_clinical_data_view(dry_run),
            "animal_model": self.create_animal_model_view(dry_run),
            "cell_line": self.create_cell_line_view(dry_run),
            "organoid": self.create_organoid_view(dry_run),
            "pdx": self.create_pdx_view(dry_run),
        }

        if not dry_run:
            logger.info("=" * 80)
            logger.info("Summary of created views:")
            for view_type, view_id in results.items():
                if view_id:
                    logger.info(f"  {view_type:15s}: {view_id}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description="Create Synapse materialized views with context-specific filters for different model types"
    )
    parser.add_argument(
        "--parent",
        default="syn26451327",
        help="Parent Synapse ID for materialized views (default: syn26451327)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without creating views"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute and create views (opposite of dry-run)"
    )
    parser.add_argument(
        "--view-type",
        choices=["clinical", "animal_model", "cell_line", "organoid", "pdx", "all"],
        default="all",
        help="Which view(s) to create (default: all)"
    )

    args = parser.parse_args()

    # Determine if this is a dry run
    dry_run = not args.execute if args.execute else args.dry_run

    # For dry-run, we don't need synapseclient
    if not dry_run and not SYNAPSE_AVAILABLE:
        logger.error("synapseclient not available. Install with: pip install synapseclient")
        return 1

    if dry_run:
        logger.info("=" * 80)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("=" * 80)
        logger.info("")

        # In dry-run mode, we don't need actual Synapse connection
        syn = None
    else:
        # Authenticate to Synapse
        logger.info("Authenticating to Synapse...")
        syn = synapseclient.Synapse()
        syn.login()
        logger.info(f"✓ Authenticated as: {syn.getUserProfile()['userName']}")

    # Create views
    creator = SynapseMaterializedViewCreator(syn, args.parent)

    if args.view_type == "all":
        results = creator.create_all_views(dry_run)
    else:
        # Create specific view
        view_methods = {
            "clinical": creator.create_clinical_data_view,
            "animal_model": creator.create_animal_model_view,
            "cell_line": creator.create_cell_line_view,
            "organoid": creator.create_organoid_view,
            "pdx": creator.create_pdx_view,
        }
        view_id = view_methods[args.view_type](dry_run)
        results = {args.view_type: view_id}

    if dry_run:
        logger.info("=" * 80)
        logger.info("Dry run complete. Run with --execute to create views.")
        logger.info("=" * 80)
    else:
        logger.info("=" * 80)
        logger.info("✓ All views created successfully!")
        logger.info("=" * 80)

    return 0


if __name__ == "__main__":
    exit(main())
