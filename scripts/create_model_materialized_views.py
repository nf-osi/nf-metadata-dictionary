#!/usr/bin/env python3
"""
Create Synapse materialized views with context-specific filters for different model types.

This script:
1. Queries the main entity view (syn16858331) for metadata annotations
2. Applies Phenopacket-inspired transformations to enrich metadata
3. Creates context-specific materialized views under parent syn26451327

Context-specific views:
- Clinical data (human patient data with HPO phenotypes from tumorType column)
- Animal model data (model organism experiments)
- Cell line data (in vitro cell systems)
- Advanced cellular models (organoids, spheroids)
- Patient-derived systems (PDX, patient-derived organoids)

Note: HPO phenotypes are determined from the tumorType column in syn16858331.

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
    """
    Enriches metadata with Phenopacket-inspired structured fields for all model types.

    HPO phenotypes are determined from the tumorType column in source view syn16858331.
    """

    def __init__(self):
        """
        Initialize with ontology mappings.

        HPO mappings are based on tumorType values from syn16858331.
        """
        # Lookup populated by build_model_db_lookup(); used to cross-reference
        # cell lines (syn26486823) and animal models (syn26486808) with clinical info.
        self.model_db_lookup: Dict[str, Dict] = {}

        # HPO mappings - Maps tumorType values to HPO codes
        # Source: tumorType column in syn16858331
        # DO NOT add codes without verification against actual HPO ontology
        self.phenotype_hpo_map = {
            # Neurofibromas — HP codes verified via hpo.jax.org
            "Plexiform Neurofibroma": "HP:0009732",
            "plexiform neurofibroma": "HP:0009732",
            "Cutaneous Neurofibroma": "HP:0001067",
            "cutaneous neurofibroma": "HP:0001067",
            "Dermal Neurofibroma": "HP:0001067",
            "dermal neurofibroma": "HP:0001067",
            "Neurofibroma": "HP:0001067",  # Generic neurofibroma
            "neurofibroma": "HP:0001067",
            "Diffuse Infiltrating Neurofibroma": "HP:0001067",  # diffuse subtype → HP:0001067
            "Localized Neurofibroma": "HP:0001067",             # localized → HP:0001067
            "Nodular Neurofibroma": "HP:0009729",               # Verified HP:0009729
            # Gliomas
            "Optic Nerve Glioma": "HP:0009734",
            "optic glioma": "HP:0009734",
            "Optic Pathway Glioma": "HP:0009734",
            "optic pathway glioma": "HP:0009734",
            # Schwannomas
            "Vestibular Schwannoma": "HP:0009589",
            "vestibular schwannoma": "HP:0009589",
            # Meningioma
            "Meningioma": "HP:0002858",
            "meningioma": "HP:0002858",
            # Spinal
            "Spinal Neurofibroma": "HP:0009735",
            "spinal neurofibroma": "HP:0009735",
            # MPNST (all grades/variants map to HP:0009733)
            "MPNST": "HP:0009733",
            "Malignant Peripheral Nerve Sheath Tumor": "HP:0009733",
            "High Grade MPNST": "HP:0009733",
            "High grade MPNST": "HP:0009733",
            "high grade MPNST": "HP:0009733",
            "high grade metastatic MPNST": "HP:0009733",
            "high grade MPNST with divergent differentiation": "HP:0009733",
            "Recurrent MPNST": "HP:0009733",
            "recurrent MPNST": "HP:0009733",
            "Atypical MPNST": "HP:0009733",
            # Schwannoma
            "Schwannoma": "HP:0100008",
            "schwannoma": "HP:0100008",
            # JMML — HP:0012209 verified via hpo.jax.org and Monarch Initiative
            "Juvenile Myelomonocytic Leukemia": "HP:0012209",
            "JMML": "HP:0012209",
        }

        # HPO code to friendly label mapping
        self.hpo_label_map = {
            "HP:0009732": "Plexiform neurofibroma",
            "HP:0001067": "Cutaneous neurofibroma",
            "HP:0009729": "Nodular neurofibroma",
            "HP:0009734": "Optic nerve glioma",
            "HP:0009589": "Vestibular schwannoma",
            "HP:0002858": "Meningioma",
            "HP:0009735": "Spinal neurofibroma",
            "HP:0009733": "Malignant peripheral nerve sheath tumor",
            "HP:0100008": "Schwannoma",
            "HP:0012209": "Juvenile myelomonocytic leukemia",
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
            # Noonan Syndrome — MONDO:0018997 verified via OBO Foundry/Monarch Initiative
            "Noonan Syndrome": "MONDO:0018997",
            "Noonan syndrome": "MONDO:0018997",
        }
        # Synonym → canonical label mapping for get_canonical_disease()
        # Used to normalize common abbreviations/synonyms to preferred display names.
        self._synonym_to_canonical = {
            "NF1": "Neurofibromatosis type 1",
            "Neurofibromatosis 1": "Neurofibromatosis type 1",
            "Neurofibromatosis type 2": "NF2-related schwannomatosis",
            "NF2": "NF2-related schwannomatosis",
            "JMML": "Juvenile myelomonocytic leukemia",
            "Noonan syndrome": "Noonan Syndrome",
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
        # These are for tumor manifestations extracted from tumorType column
        self.manifestation_mondo_map = {
            "atypical neurofibroma": "MONDO:0003306",
            "Atypical Neurofibroma": "MONDO:0003306",
            # ANNUBP is the same concept (NCIT:C178255 cross-references MONDO:0003306)
            "ANNUBP": "MONDO:0003306",
        }

        # NCIT codes verified via NCI EVS REST API (api-evsrest.nci.nih.gov)
        self.manifestation_ncit_map = {
            # MPNST — C9030 is High Grade specifically; C3798 is generic MPNST
            "High Grade Malignant Peripheral Nerve Sheath Tumor": "NCIT:C9030",
            "High Grade MPNST": "NCIT:C9030",
            "High grade MPNST": "NCIT:C9030",
            "high grade MPNST": "NCIT:C9030",
            "high grade metastatic MPNST": "NCIT:C9030",
            "high grade MPNST with divergent differentiation": "NCIT:C9030",
            "Malignant Peripheral Nerve Sheath Tumor": "NCIT:C3798",  # generic MPNST
            "MPNST": "NCIT:C3798",
            "Atypical MPNST": "NCIT:C3798",                           # no distinct code; use generic
            "Recurrent MPNST": "NCIT:C8823",                          # C8823 = Recurrent MPNST (verified)
            "recurrent MPNST": "NCIT:C8823",
            # Schwannomas
            "Vestibular Schwannoma": "NCIT:C3276",
            "vestibular schwannoma": "NCIT:C3276",
            "Acoustic Neuroma": "NCIT:C3276",
            "Sporadic Schwannoma": "NCIT:C129278",
            "Schwannoma": "NCIT:C3269",  # Generic schwannoma
            "schwannoma": "NCIT:C3269",
            # Neurofibromas — C3797 = Plexiform NF (verified); C3272 = generic NF
            "Plexiform Neurofibroma": "NCIT:C3797",                   # was C3798 (wrong)
            "plexiform neurofibroma": "NCIT:C3797",
            "Neurofibroma": "NCIT:C3272",                              # Generic
            "neurofibroma": "NCIT:C3272",
            "Diffuse Infiltrating Neurofibroma": "NCIT:C8426",         # C8426 = Diffuse Neurofibroma (verified)
            "Localized Neurofibroma": "NCIT:C3272",                    # no distinct code; use generic NF
            # ANNUBP — C178255 verified via NCI EVS
            "ANNUBP": "NCIT:C178255",
            # Meningioma
            "Meningioma": "NCIT:C3230",
            "meningioma": "NCIT:C3230",
            # Gliomas
            "Optic Nerve Glioma": "NCIT:C4688",
            "optic glioma": "NCIT:C4688",
            "Optic Pathway Glioma": "NCIT:C4537",
            "optic pathway glioma": "NCIT:C4537",
            "Low-Grade Glioma": "NCIT:C4936",
            "Low Grade Glioma": "NCIT:C4936",
            "Low-Grade Glioma NOS": "NCIT:C132067",                    # C132067 = Low Grade Glioma (verified)
            "High-Grade Glioma": "NCIT:C4051",
            "High Grade Glioma": "NCIT:C4051",
            "High-Grade Glioma NOS": "NCIT:C4822",                     # C4822 = Malignant Glioma (verified)
            "Glioma": "NCIT:C3058",                                    # generic glioma
            "Pilocytic Astrocytoma": "NCIT:C4047",                     # was C3798 (wrong); C4047 = WHO Grade 1
            "Pilomyxoid Astrocytoma": "NCIT:C40315",                   # C40315 verified
            "Diffuse Astrocytoma": "NCIT:C7173",                       # C7173 verified
            "Glioblastoma": "NCIT:C3058",                              # C3058 verified
            "Glioblastoma Multiforme": "NCIT:C3058",                   # synonym of Glioblastoma
            # Hematologic
            "Juvenile Myelomonocytic Leukemia": "NCIT:C9233",          # C9233 verified
            "JMML": "NCIT:C9233",
            # Other tumors
            "Fibromatosis": "NCIT:C3042",                              # C3042 verified
            "Melanoma": "NCIT:C3224",                                  # C3224 verified
            "Sarcoma": "NCIT:C9118",
            "sarcoma": "NCIT:C9118",
        }

        self.manifestation_omim_map = {
            # OMIM codes for tumor manifestations (if applicable)
            "Juvenile Myelomonocytic Leukemia": "OMIM:607785",
            "JMML": "OMIM:607785",
        }

        # Build case-insensitive lookup for diseases
        self._disease_lookup_normalized = {}
        for disease, code in self.disease_mondo_map.items():
            self._disease_lookup_normalized[disease.lower().strip()] = (disease, code, "MONDO")

    def build_model_db_lookup(
        self,
        syn,
        cell_line_table: str = "syn26486823",
        animal_model_table: str = "syn26486808",
    ) -> None:
        """
        Load clinical/model info from NF Research Tools Central into self.model_db_lookup.

        Cell lines (syn26486823) are keyed by individualID.
        Animal models (syn26486808) are keyed by modelSystemName.
        Used to enrich cell_line, animal_model, and pdx views with NF type info
        when the base file annotation does not carry a diagnosis field.

        Args:
            syn: Authenticated Synapse client
            cell_line_table: Synapse ID for cell lines table (default: syn26486823)
            animal_model_table: Synapse ID for animal models table (default: syn26486808)
        """
        lookup = {}
        for table_id in (cell_line_table, animal_model_table):
            try:
                results = syn.tableQuery(f"SELECT * FROM {table_id} LIMIT 10000")
                df = results.asDataFrame()
                # Identify the name key column — try common names used in NFTC schema
                key_col = next(
                    (c for c in df.columns if c.lower() in (
                        "resourcename", "individualid", "modelsystemname", "name", "celllinename"
                    )),
                    df.columns[0] if len(df.columns) > 0 else None
                )
                if key_col is None:
                    continue
                for _, record in df.iterrows():
                    key = str(record.get(key_col, "")).strip()
                    if key:
                        lookup[key] = dict(record)
                logger.info(f"Loaded {len(df)} records from {table_id} for cross-referencing")
            except Exception as e:
                logger.warning(f"Could not load model DB from {table_id}: {e}")
        self.model_db_lookup = lookup

    def get_nf_type_from_lookup(self, key: Optional[str]) -> Optional[str]:
        """
        Return NF disease type for a cell line or animal model from the NFTC lookup.
        Tries common column name variants used in nf-research-tools-schema.
        """
        if not key or key not in self.model_db_lookup:
            return None
        record = self.model_db_lookup[key]
        for col in ("diagnosis", "nfType", "disease", "nf_type", "NF Type", "diseaseFocus"):
            val = record.get(col)
            if val and str(val).strip().lower() not in ("", "nan", "none", "unknown"):
                return str(val).strip()
        return None

    def get_model_db_fields(self, key: Optional[str]) -> Dict[str, Optional[str]]:
        """
        Return a dict of clinical/model fields for a cell line or animal model from NFTC.

        Used to backfill enriched columns when base file annotations in syn16858331
        are missing. Tries common column name variants from nf-research-tools-schema.

        Returns:
            Dict with keys: nf_type, tissue, sex, tumor_type (all Optional[str])
        """
        empty: Dict[str, Optional[str]] = {
            "nf_type": None, "tissue": None, "sex": None, "tumor_type": None
        }
        if not key or key not in self.model_db_lookup:
            return empty
        record = self.model_db_lookup[key]

        def _get(*cols: str) -> Optional[str]:
            for col in cols:
                val = record.get(col)
                if val and str(val).strip().lower() not in ("", "nan", "none", "unknown"):
                    return str(val).strip()
            return None

        return {
            "nf_type": _get("diagnosis", "nfType", "disease", "nf_type", "NF Type", "diseaseFocus"),
            "tissue": _get("tissue", "tissueOfOrigin", "tissue_of_origin", "primaryTissue"),
            "sex": _get("sex", "donorSex", "gender"),
            "tumor_type": _get("tumorType", "tumor", "tumor_type", "tumorTypeOfOrigin"),
        }

    def extract_present_phenotypes(self, row: Dict) -> List[str]:
        """
        Extract list of HPO terms for present phenotypes from tumorType column.

        Args:
            row: Data row with tumorType field

        Returns:
            List of HPO codes for present phenotypes
        """
        present_hpo = []

        # Get tumorType value from row
        tumor_type = row.get("tumorType")
        if not tumor_type:
            return present_hpo

        # Handle JSON arrays or lists (tumorType may contain multiple values)
        tumor_types = []
        if isinstance(tumor_type, list):
            tumor_types = tumor_type
        elif isinstance(tumor_type, str):
            # Try parsing as JSON array if it looks like one
            if tumor_type.startswith('['):
                try:
                    tumor_types = json.loads(tumor_type)
                except json.JSONDecodeError:
                    tumor_types = [tumor_type]
            else:
                tumor_types = [tumor_type]

        # Map each tumor type to HPO code
        for tt in tumor_types:
            if not tt:
                continue
            tt_str = str(tt).strip()
            if not tt_str:
                continue

            # Look up HPO code for this tumor type
            hpo_code = self.phenotype_hpo_map.get(tt_str)
            if hpo_code and hpo_code not in present_hpo:
                present_hpo.append(hpo_code)

        return present_hpo

    def extract_phenotype_labels(self, hpo_codes: List[str]) -> List[str]:
        """Convert HPO codes to friendly labels."""
        labels = []
        for code in hpo_codes:
            label = self.hpo_label_map.get(code, code)  # Fallback to code if no label
            labels.append(label)
        return labels

    def extract_tumor_ncit_codes(self, row: Dict) -> List[str]:
        """
        Extract NCIT codes for tumor manifestations from tumorType column.

        Args:
            row: Data row with tumorType field

        Returns:
            List of NCIT codes for tumor manifestations
        """
        ncit_codes = []

        # Get tumorType value from row
        tumor_type = row.get("tumorType")
        if not tumor_type:
            return ncit_codes

        # Handle JSON arrays or lists
        tumor_types = []
        if isinstance(tumor_type, list):
            tumor_types = tumor_type
        elif isinstance(tumor_type, str):
            if tumor_type.startswith('['):
                try:
                    tumor_types = json.loads(tumor_type)
                except json.JSONDecodeError:
                    tumor_types = [tumor_type]
            else:
                tumor_types = [tumor_type]

        # Map each tumor type to NCIT code
        for tt in tumor_types:
            if not tt:
                continue
            tt_str = str(tt).strip()
            if not tt_str:
                continue

            # Look up NCIT code for this tumor type
            ncit_code = self.manifestation_ncit_map.get(tt_str)
            if ncit_code and ncit_code not in ncit_codes:
                ncit_codes.append(ncit_code)

        return ncit_codes

    def extract_tumor_mondo_codes(self, row: Dict) -> List[str]:
        """
        Extract MONDO codes for tumor manifestations from tumorType column.

        Args:
            row: Data row with tumorType field

        Returns:
            List of MONDO codes for tumor manifestations
        """
        mondo_codes = []

        # Get tumorType value from row
        tumor_type = row.get("tumorType")
        if not tumor_type:
            return mondo_codes

        # Handle JSON arrays or lists
        tumor_types = []
        if isinstance(tumor_type, list):
            tumor_types = tumor_type
        elif isinstance(tumor_type, str):
            if tumor_type.startswith('['):
                try:
                    tumor_types = json.loads(tumor_type)
                except json.JSONDecodeError:
                    tumor_types = [tumor_type]
            else:
                tumor_types = [tumor_type]

        # Map each tumor type to MONDO code
        for tt in tumor_types:
            if not tt:
                continue
            tt_str = str(tt).strip()
            if not tt_str:
                continue

            # Look up MONDO code for this tumor type
            mondo_code = self.manifestation_mondo_map.get(tt_str)
            if mondo_code and mondo_code not in mondo_codes:
                mondo_codes.append(mondo_code)

        return mondo_codes

    def extract_tumor_omim_codes(self, row: Dict) -> List[str]:
        """
        Extract OMIM codes for tumor manifestations from tumorType column.

        Args:
            row: Data row with tumorType field

        Returns:
            List of OMIM codes for tumor manifestations
        """
        omim_codes = []

        # Get tumorType value from row
        tumor_type = row.get("tumorType")
        if not tumor_type:
            return omim_codes

        # Handle JSON arrays or lists
        tumor_types = []
        if isinstance(tumor_type, list):
            tumor_types = tumor_type
        elif isinstance(tumor_type, str):
            if tumor_type.startswith('['):
                try:
                    tumor_types = json.loads(tumor_type)
                except json.JSONDecodeError:
                    tumor_types = [tumor_type]
            else:
                tumor_types = [tumor_type]

        # Map each tumor type to OMIM code
        for tt in tumor_types:
            if not tt:
                continue
            tt_str = str(tt).strip()
            if not tt_str:
                continue

            # Look up OMIM code for this tumor type
            omim_code = self.manifestation_omim_map.get(tt_str)
            if omim_code and omim_code not in omim_codes:
                omim_codes.append(omim_code)

        return omim_codes

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

        Synonyms (NF1, NF2, JMML, etc.) are normalized to their preferred display
        names so facet filters are consistent across studies using different naming.

        Args:
            diagnosis: Diagnosis string from data (may be synonym or different case)

        Returns:
            Canonical disease label or original if no mapping found
        """
        if not diagnosis:
            return None

        # Check synonym→canonical map first (NF1→Neurofibromatosis type 1, etc.)
        if diagnosis in self._synonym_to_canonical:
            return self._synonym_to_canonical[diagnosis]

        # Canonical names map to themselves
        if diagnosis in self.disease_mondo_map and diagnosis not in self._synonym_to_canonical.values():
            # Only return as-is if it's a true canonical name (not an alias)
            return diagnosis

        # Try case-insensitive match
        normalized = diagnosis.lower().strip()
        if normalized in self._disease_lookup_normalized:
            canonical, _, _ = self._disease_lookup_normalized[normalized]
            # Apply synonym normalization to the resolved canonical form too
            return self._synonym_to_canonical.get(canonical, canonical)

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

        # HPO phenotypes - determined from tumorType column
        # Extracts both HPO codes and human-readable labels
        present_hpo_codes = self.extract_present_phenotypes(row)
        phenotype_labels = self.extract_phenotype_labels(present_hpo_codes)

        enriched["Phenotypes"] = json.dumps(phenotype_labels) if phenotype_labels else None
        enriched["Phenotype HPO Codes"] = json.dumps(present_hpo_codes) if present_hpo_codes else None
        enriched["Phenotype Count"] = len(present_hpo_codes)

        # Tumor manifestation ontology codes - also from tumorType column
        tumor_ncit_codes = self.extract_tumor_ncit_codes(row)
        tumor_mondo_codes = self.extract_tumor_mondo_codes(row)
        tumor_omim_codes = self.extract_tumor_omim_codes(row)

        enriched["Tumor Type NCIT Codes"] = json.dumps(tumor_ncit_codes) if tumor_ncit_codes else None
        enriched["Tumor Type MONDO Codes"] = json.dumps(tumor_mondo_codes) if tumor_mondo_codes else None
        enriched["Tumor Type OMIM Codes"] = json.dumps(tumor_omim_codes) if tumor_omim_codes else None

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

        # HumanCohortTemplate manifestation fields — pass through as-is from annotations
        if enriched["Data Context"] == "clinical":
            for field in ALL_MANIFESTATION_FIELDS:
                val = row.get(field)
                if val is not None and str(val).lower() not in ("nan", "none", ""):
                    enriched[field] = val

        # For non-clinical views: cross-reference NFTC to get NF disease type and
        # additional clinical metadata when the file annotation lacks these fields.
        # Cell lines (syn26486823) keyed by individualID; models (syn26486808) by modelSystemName.
        if enriched["Data Context"] in ("cell_line", "animal_model", "pdx", "organoid"):
            context = enriched["Data Context"]
            lookup_key = row.get("individualID") if context == "cell_line" else row.get("modelSystemName")
            db_fields = self.get_model_db_fields(lookup_key)

            # NF Type: prefer already-resolved Diagnosis annotation, fall back to NFTC lookup
            if enriched.get("Diagnosis"):
                enriched["NF Type"] = enriched["Diagnosis"]
            elif db_fields["nf_type"]:
                enriched["NF Type"] = db_fields["nf_type"]

            # Cell line-specific: enrich tissue and sex from syn26486823 when not annotated
            if context == "cell_line":
                base_tissue = row.get("tissue")
                if base_tissue and str(base_tissue).strip().lower() not in ("", "nan", "none"):
                    enriched["Tissue of Origin"] = str(base_tissue).strip()
                elif db_fields["tissue"]:
                    enriched["Tissue of Origin"] = db_fields["tissue"]

                base_sex = row.get("sex")
                if not base_sex or str(base_sex).strip().lower() in ("", "nan", "none"):
                    if db_fields["sex"]:
                        enriched["sex"] = db_fields["sex"]

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


# HumanCohortTemplate manifestation fields (from REiNS Table 2)
# These are stored as annotations on Synapse files and surfaced as facets in the clinical view.
# Grouped by NF subtype for clarity; all use enumeration faceting.
NF1_PRESENCE_FIELDS = [
    # Simple absent/present/unknown (PresenceEnum)
    "cafeaulaitMacules",
    "skinFoldFreckling",
    "IrisLischNodules",
    "heartDefect",
    "vascularDisease",
    "peripheralNeuropathy",
    "aqueductalStenosis",
    "longBoneDysplasia",
    "sphenoidDysplasia",
    "scoliosis",
    "intellectualDisability",
    "learningDisability",
    "attentionDeficitDisorder",
    "pheochromocytoma",
    "glomusTumor",
    "MPNSTCharacterization",
    "nonopticGlioma",
    "GIST",
    "leukemia",
    "breastCancer",
    "otherTumors",
]
NF1_NEUROFIBROMA_FIELDS = [
    # absent/scattered/dense/unknown (NeurofibromaManifestationEnum)
    "dermalNeurofibromas",
    "subcutaneousNodularNeurofibromas",
    "diffuseDermalNeurofibromas",
]
NF1_COMPLEX_FIELDS = [
    # Richer enums specific to NF1 manifestations
    "spinalNeurofibromas",
    "plexiformNeurofibromas",
    "opticGlioma",
    "pubertyOnset",
    "stature",
]
NF2_FIELDS = [
    # Imaging-based manifestation enums for NF2
    "vestibularSchwannoma",
    "meningioma",
    "gliomaOrEpendymoma",
    "spinalSchwannoma",
    "dermalSchwannoma",
    "nonvestibularCranialSchwannoma",
    "lenticularOpacity",
]
SCHWANNOMATOSIS_FIELDS = [
    "nonvestibularSchwannomas",
    "numberOfSchwannomas",
]
ALL_MANIFESTATION_FIELDS = (
    NF1_PRESENCE_FIELDS
    + NF1_NEUROFIBROMA_FIELDS
    + NF1_COMPLEX_FIELDS
    + NF2_FIELDS
    + SCHWANNOMATOSIS_FIELDS
)


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
        self.source_view_id = "syn16858331"
        self.enricher = ModelMetadataEnricher()
        # Pre-load NFTC model DB for cross-referencing cell lines and animal models.
        # Skipped in dry-run mode (syn is None) — lookup will be empty but schema is valid.
        if syn is not None:
            self.enricher.build_model_db_lookup(syn)

    def define_enriched_columns(self, view_type: str = "all") -> List:
        """
        Define additional computed columns for a context-specific view.

        Columns are scoped by view_type to avoid unnecessary column bloat and stay
        within Synapse's 152-column limit per materialized view.

        Args:
            view_type: One of 'clinical', 'animal_model', 'cell_line', 'organoid', 'pdx'

        Note on Synapse API limit: 64KB per row; base columns ~10-20KB, enriched ~2-4KB.
        """
        if SYNAPSE_AVAILABLE:
            # Columns present in every view
            columns = [
                Column(name="Data Context", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Diagnosis", columnType=ColumnType.STRING, maximumSize=200, facetType="enumeration"),
                Column(name="Diagnosis MONDO Code", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Diagnosis NCIT Code", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Has Treatment", columnType=ColumnType.BOOLEAN, facetType="enumeration"),
                Column(name="Age Group", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
                Column(name="Model Type", columnType=ColumnType.STRING, maximumSize=50, facetType="enumeration"),
            ]
            if view_type == "clinical":
                # Phenotype enrichment from tumorType (clinical-only — rich HPO/ontology mapping)
                columns += [
                    Column(name="Phenotypes", columnType=ColumnType.STRING, maximumSize=2000, facetType="enumeration"),
                    Column(name="Phenotype HPO Codes", columnType=ColumnType.STRING, maximumSize=1000),
                    Column(name="Phenotype Count", columnType=ColumnType.INTEGER, facetType="range"),
                    Column(name="Tumor Type NCIT Codes", columnType=ColumnType.STRING, maximumSize=500),
                    Column(name="Tumor Type MONDO Codes", columnType=ColumnType.STRING, maximumSize=500),
                    Column(name="Tumor Type OMIM Codes", columnType=ColumnType.STRING, maximumSize=500),
                ]
                # HumanCohortTemplate manifestation fields — explicit faceting for clinical filters
                for field in ALL_MANIFESTATION_FIELDS:
                    columns.append(Column(
                        name=field,
                        columnType=ColumnType.STRING,
                        maximumSize=100,
                        facetType="enumeration",
                    ))
            else:
                # Non-clinical views: NF type cross-referenced from NFTC (syn26486823/syn26486808)
                # when the base file annotation lacks a diagnosis field.
                columns.append(Column(
                    name="NF Type",
                    columnType=ColumnType.STRING,
                    maximumSize=200,
                    facetType="enumeration",
                ))
                if view_type == "cell_line":
                    # Tissue of origin cross-referenced from syn26486823 (cell line DB),
                    # backfilling the often-sparse base tissue annotation.
                    columns.append(Column(
                        name="Tissue of Origin",
                        columnType=ColumnType.STRING,
                        maximumSize=200,
                        facetType="enumeration",
                    ))
            return columns
        else:
            # Return column specs as dicts for dry-run
            columns = [
                {"name": "Data Context", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Diagnosis", "type": "STRING(200)", "facet": "enumeration"},
                {"name": "Diagnosis MONDO Code", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Diagnosis NCIT Code", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Has Treatment", "type": "BOOLEAN", "facet": "enumeration"},
                {"name": "Age Group", "type": "STRING(50)", "facet": "enumeration"},
                {"name": "Model Type", "type": "STRING(50)", "facet": "enumeration"},
            ]
            if view_type == "clinical":
                columns += [
                    {"name": "Phenotypes", "type": "STRING(2000)", "facet": "enumeration"},
                    {"name": "Phenotype HPO Codes", "type": "STRING(1000)", "facet": None},
                    {"name": "Phenotype Count", "type": "INTEGER", "facet": "range"},
                    {"name": "Tumor Type NCIT Codes", "type": "STRING(500)", "facet": None},
                    {"name": "Tumor Type MONDO Codes", "type": "STRING(500)", "facet": None},
                    {"name": "Tumor Type OMIM Codes", "type": "STRING(500)", "facet": None},
                ]
                for field in ALL_MANIFESTATION_FIELDS:
                    columns.append({"name": field, "type": "STRING(100)", "facet": "enumeration"})
            else:
                columns.append({"name": "NF Type", "type": "STRING(200)", "facet": "enumeration"})
                if view_type == "cell_line":
                    columns.append({"name": "Tissue of Origin", "type": "STRING(200)", "facet": "enumeration"})
            return columns

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

        # View-specific facets — only columns that exist in syn16858331 or are enriched columns.
        # Columns verified against base view headers: species, diagnosis, tumorType, tissue,
        # modelSystemName, genePerturbed, genePerturbationType, nf1Genotype, nf2Genotype,
        # sex, cellType, transplantationType, vitalStatus are all present.
        # NOT in base view: specimenType, cellLineCategory, bodySite.
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
            ] + ALL_MANIFESTATION_FIELDS,
            "animal_model": [
                "NF Type",
                "Diagnosis",
                "Model Type",
                "species",
                "modelSystemName",
                "genePerturbed",
                "genePerturbationType",
                "nf1Genotype",
                "nf2Genotype",
                "tissue",
                "Has Treatment",
            ],
            "cell_line": [
                "NF Type",
                "Diagnosis",
                "Tissue of Origin",
                "tumorType",
                "nf1Genotype",
                "nf2Genotype",
                "sex",
                "cellType",
                "Has Treatment",
            ],
            "organoid": [
                "NF Type",
                "Diagnosis",
                "modelSystemName",
                "tumorType",
                "tissue",
            ],
            "pdx": [
                "NF Type",
                "Diagnosis",
                "transplantationType",
                "tumorType",
                "modelSystemName",
                "species",
            ],
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
        view_columns = self.define_enriched_columns(view_type="clinical")

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
        view_columns = self.define_enriched_columns(view_type="animal_model")
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
        view_columns = self.define_enriched_columns(view_type="cell_line")
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
        view_columns = self.define_enriched_columns(view_type="organoid")
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
        view_columns = self.define_enriched_columns(view_type="pdx")
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
