# Display Name Fix for Schematic Conversion Issue

## Problem

The `schematic schema convert` command removes `sms:displayName` fields from certain JSON-LD entries, particularly those with spaces in their names. This causes manifest generation to fail with a `KeyError: 'sms:displayName'` error.

Entries affected include:
- `129T2/SvEmsJ::C57Bl/6NTac Nf1+/+`
- `129T2/SvEmsJ::C57Bl/6NTac Nf1+/-`

## Root Cause

The issue occurs during the conversion from "bb flavored JSONLD to schematic flavored JSONLD" when `schematic schema convert` processes the JSON-LD file. The schematic library's `label_to_dn_dict` method in `data_model_parser.py` expects all entries to have a `sms:displayName` field, but some entries lose this field during conversion.

## Solution

We implemented a two-part fix:

### 1. Modified Build Process (Makefile)

The `NF.jsonld` target now:
1. Generates JSON-LD with retold → `retold_NF.jsonld` (preserves all displayNames)
2. Copies it to `NF.jsonld` for schematic processing

### 2. Post-Schematic Fix (GitHub Actions)

After `schematic schema convert` runs, we use `utils/fix_display_names.py` to:
1. Extract display name mappings from the original retold output
2. Add missing `sms:displayName` fields back to entries that lost them
3. Preserve the correct display names with spaces

### 3. Automated Integration

The fix is integrated into `.github/workflows/main-ci.yml`:

```yaml
- name: Setup schematic and do another convert pass
  run: |
    pip install schematicpy==${{ env.SCHEMATIC_VERSION }}
    schematic schema convert NF.jsonld
    python utils/fix_display_names.py retold_NF.jsonld NF.jsonld
```

## Files Modified

- `Makefile` - Updated NF.jsonld target to preserve retold output
- `.github/workflows/main-ci.yml` - Added fix step after schematic conversion  
- `utils/fix_display_names.py` - New script to restore missing displayNames
- `.gitignore` - Added `retold_NF.jsonld` to ignored files

## Testing

The fix successfully restores `sms:displayName` fields for the problematic entries:

```json
{
  "@id": "bts:129T2/SvEmsJ::C57Bl/6NTacNf1+/+",
  "sms:displayName": "129T2/SvEmsJ::C57Bl/6NTac Nf1+/+"
}
```

This ensures manifest generation works correctly and preserves the important biological meaning of model system names that contain special characters like `::`, `/`, and `+`.