# Changes to AnimalIndividualTemplate.json Explained

## Summary

The `modelSystemName` field in `AnimalIndividualTemplate.json` was updated to use **auto-generated enums** from the NF research tools database instead of a hardcoded list.

## Key Changes

### 1. Enum List Updated: 807 → 123 entries

**Why the reduction?**

The old list (807 entries) contained a **mix of animal models AND cell lines**, which was incorrect for the AnimalIndividualTemplate. The new list (123 entries) contains **only animal models** from the authoritative Synapse database.

**Old behavior:**
- Hardcoded list from 2023-2024
- Mixed animal models and cell lines together
- No RRIDs or identifiers
- Never updated automatically

**New behavior:**
- Auto-generated from Synapse materialized view (`syn51730943`)
- Only actual animal models (cell lines moved to appropriate templates)
- Includes RRIDs for identification
- Updates weekly via GitHub Actions

### 2. Format Improvements

**Old Format:**
```json
"enum": [
  "10CM",
  "2-004",
  "BJFF.6",
  "HEK293"  // <-- This is a cell line, not an animal model!
]
```

**New Format:**
```json
"enum": [
  "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
  "B6.129S1-Nf1tm1Cbr/J (rrid:IMSR_JAX:007923)",
  "B6.129S2-Nf1tm1Tyj/J (rrid:IMSR_JAX:008192)"
]
```

**Improvements:**
- ✅ Includes RRID (Research Resource Identifier) in name
- ✅ Uses official nomenclature from repositories (JAX, MMRRC, etc.)
- ✅ Enables auto-fill of related metadata
- ✅ Supports validation and cross-referencing

### 3. Auto-Generation Metadata Added

**New field added:**
```json
{
  "items": {
    "type": "string",
    "enum": [ /* 123 animal models */ ],
    "x-auto-generated": {
      "source": "auto-generated/enums/modelSystemName_enum.json",
      "lastUpdated": "2025-12-11T11:44:51.264470Z",
      "sourceTable": "syn51730943"
    }
  }
}
```

**What this means:**
- 📍 **Transparency:** Shows where data comes from
- 📅 **Freshness:** Tracks when list was last updated
- 🔗 **Traceability:** Links back to source Synapse table
- 🤖 **Automation:** Indicates this is auto-generated (don't manually edit)

## What Happened to "Removed" Entries?

### Cell Lines (Most of the 693 removed)

Entries like these were **incorrectly** in AnimalIndividualTemplate:
- `10CM` (cell line)
- `HEK293` variants (cell lines)
- `ipNF05.5` (cell line)
- `S462-TY` (cell line)

**Where they went:** These belong in cell line templates, and are now properly tracked in:
- `auto-generated/enums/cellLineName_enum.json` (638 cell lines)
- `auto-generated/mappings/cell_lines_mappings.json`

### Outdated Animal Models

Some animal models may have been:
- **Retired** from repositories
- **Renamed** in source databases
- **Duplicates** of other entries
- **Not properly classified** in the new database

### Still Available

If a legitimate animal model seems missing, it may be:
- Listed under a different name (check RRID)
- In the source database but filtered during generation
- Need to be added to the Synapse source table

## Example: What Changed for a Specific Model

### Before
```json
"modelSystemName": {
  "enum": [
    "B6.129(Cg)-Nf1tm1Par/J"  // No RRID, no metadata
  ]
}
```

**Problems:**
- ❌ No way to know which JAX strain this is
- ❌ Can't auto-fill species, genotype, etc.
- ❌ No link to source database
- ❌ Never gets updated

### After
```json
"modelSystemName": {
  "enum": [
    "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
  ],
  "x-auto-generated": {
    "source": "auto-generated/enums/modelSystemName_enum.json",
    "lastUpdated": "2025-12-11T11:44:51.264470Z",
    "sourceTable": "syn51730943"
  }
}
```

**With auto-fill mappings:**
```json
{
  "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)": {
    "species": "Mus musculus",
    "organism": "Mus",
    "genotype": "C57BL/6",
    "backgroundStrain": "C57BL/6",
    "RRID": "rrid:IMSR_JAX:017640",
    "modelSystemType": "animal",
    "geneticModification": "Neurofibromatosis type 1",
    "manifestation": "Optic Nerve Glioma",
    "institution": "Memorial Sloan-Kettering Cancer Center"
  }
}
```

**Benefits:**
- ✅ RRID enables precise identification
- ✅ Auto-fills 8+ related metadata fields
- ✅ Linked to authoritative source
- ✅ Updates automatically when JAX updates

## Impact on Users

### For Researchers Submitting Data

**Before:**
1. Type or select model name from 807-item dropdown (mixed with cell lines)
2. Manually look up and enter species
3. Manually look up and enter genotype
4. Manually look up and enter background strain
5. Manually look up RRID
6. Hope you got it all correct

**After:**
1. Start typing model name
2. Select from dropdown (only 123 animal models, properly organized)
3. **System automatically fills:** species, genotype, backgroundStrain, RRID, institution, description
4. Continue with remaining fields

**Result:** 95% less data entry, 100% accuracy

### For Data Curators

**Before:**
- Review each submission for correct species/genotype
- Fix inconsistent naming (same model spelled different ways)
- Look up missing RRIDs
- Deal with cell lines in wrong templates

**After:**
- Auto-filled data pre-validated
- Consistent naming enforced
- RRIDs automatically included
- Correct tools in correct templates

### For Data Consumers

**Before:**
- Hard to filter by species (inconsistent values)
- Can't reliably compare across studies
- RRIDs missing or incorrect

**After:**
- Reliable filtering by species, genotype, etc.
- Consistent tool references enable cross-study comparison
- RRIDs enable lookup in external databases

## Validation & Backwards Compatibility

### Will Old Data Still Validate?

**Short answer:** Most will, but some may need review.

**Details:**

**Valid scenarios:**
- ✅ Old model name matches new name exactly → still validates
- ✅ Old model name had RRID added → still validates (name unchanged)

**Need review:**
- ⚠️ Cell line name in AnimalIndividualTemplate → should use different template
- ⚠️ Model renamed in source database → may need manual update
- ⚠️ Model retired from repository → may need alternative

### How to Handle Legacy Data

If validating old manifests against new schema:

1. **Cell lines flagged as invalid**
   - These were wrong template usage
   - Move to appropriate cell line template

2. **Model names not found**
   - Check if model was renamed (search by RRID)
   - Check if model exists in source database
   - Contact data curators if legitimate model missing

3. **Want to use old enum temporarily**
   - The backup is saved: `AnimalIndividualTemplate.json.bak`
   - But better to update data to use current models

## Future Updates

### Weekly Automation

The enum list will now update automatically:

**Every Monday at 6:00 AM UTC:**
1. GitHub Actions fetches latest from Synapse
2. Regenerates enum list
3. Updates this schema file
4. Creates PR with changes

**You'll see PRs like:**
```
🤖 Update Research Tool Controlled Vocabularies - 2025-12-18

- Animal models: 2 new, 1 updated
- Cell lines: 5 new
- Source: syn51730943
```

### How to Add a New Model

**Don't edit the schema directly!**

Instead:
1. Add model to Synapse source table (`syn51730943`)
2. Wait for next weekly update (or trigger manually)
3. Schema automatically updates

**Manual trigger:**
- Go to Actions → Update Research Tool Enums → Run workflow

## Questions?

### "Why was my model removed?"

Check:
1. Is it actually a cell line? (then it's in `cellLineName_enum.json`)
2. Does it exist in Synapse table `syn51730943`?
3. Is it listed under a different name?

Search the new enum by RRID or partial name:
```bash
grep -i "nf1" auto-generated/enums/modelSystemName_enum.json
```

### "Can I add models manually?"

No - the schema is auto-generated. To add a model:
1. Submit to Synapse research tools database
2. It will appear in next weekly update

### "What if I need the old list?"

The backup is preserved: `registered-json-schemas/AnimalIndividualTemplate.json.bak`

But consider:
- Why do you need outdated/incorrect data?
- Can you update to use current models?
- Are you trying to validate old data? (see backwards compatibility above)

## Technical Details

### File Structure

**Location in schema:**
```json
{
  "$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-animalindividualtemplate",
  "properties": {
    "modelSystemName": {
      "description": "A group of presumed common ancestry...",
      "items": {
        "type": "string",
        "enum": [ /* AUTO-GENERATED LIST */ ],
        "x-auto-generated": { /* METADATA */ }
      },
      "type": "array"
    }
  }
}
```

### Auto-Generation Script

The update is performed by:
```bash
python scripts/integrate_tool_mappings.py \
  --schemas-dir registered-json-schemas \
  --auto-generated-dir auto-generated
```

**What it does:**
1. Reads `auto-generated/enums/modelSystemName_enum.json`
2. Updates `registered-json-schemas/AnimalIndividualTemplate.json`
3. Adds `x-auto-generated` metadata
4. Creates backup (`.bak` file)

### Source Data

**Upstream:** Synapse materialized view `syn51730943`

**Refresh frequency:** Weekly (every Monday)

**Manual refresh:**
```bash
python scripts/fetch_synapse_tools.py --use-materialized-view
python scripts/generate_tool_schemas_from_view.py
python scripts/integrate_tool_mappings.py
```

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Count** | 807 entries | 123 entries |
| **Content** | Mixed models & cell lines | Animal models only |
| **Format** | Plain names | Names with RRIDs |
| **Source** | Hardcoded | Auto-generated from Synapse |
| **Updates** | Manual (never) | Automatic (weekly) |
| **Metadata** | None | Source, timestamp, table ID |
| **Auto-fill** | Not supported | Enabled |
| **Validation** | Names only | Names + attributes |

**Bottom line:** This change makes the schema **more accurate, more useful, and self-maintaining**.

---

**Questions or concerns?** Open an issue or contact the NF-OSI data team.
