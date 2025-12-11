# Changelog - Auto-Generated Research Tool Schemas

All notable changes to the auto-generated research tool schemas are documented in this file.

This file is automatically updated when changes are detected in the source Synapse tables.

## Format

Each entry includes:
- **Date:** When the update was generated
- **Changes:** Summary of additions, modifications, and removals
- **Source:** Link to the pull request containing the changes

---

## [Unreleased]

Initial setup of automated research tools integration.

### Added
- Automated pipeline to fetch research tool metadata from Synapse
- JSON Schema enumerations for controlled vocabularies
- Attribute mappings for auto-fill functionality
- GitHub Actions workflow for weekly updates
- Validation system for generated schemas

### Tool Types Supported
- Animal Models (modelSystemName)
- Cell Lines (cellLineName)
- Antibodies (antibodyName)
- Genetic Reagents (reagentName)
- Biobanks (biobank)

---

## Future Updates

Updates will be automatically appended below when the GitHub Actions workflow detects changes in the source Synapse tables.

Each update entry will follow this format:

```
## [YYYY-MM-DD] - PR #XXX

### Animal Models
- Added: X new models
- Updated: Y existing models
- Removed: Z deprecated models

### Cell Lines
- Added: X new lines
- Updated: Y existing lines
- Removed: Z deprecated lines

### Antibodies
- Added: X new antibodies
- Updated: Y existing antibodies
- Removed: Z deprecated antibodies

### Genetic Reagents
- Added: X new reagents
- Updated: Y existing reagents
- Removed: Z deprecated reagents

### Biobanks
- Added: X new biobanks
- Updated: Y existing biobanks
- Removed: Z deprecated biobanks

### Notes
- Any special considerations or breaking changes
```

---

**Note:** This changelog tracks changes to the auto-generated files. For changes to the generation scripts or workflow, see the main repository changelog.
