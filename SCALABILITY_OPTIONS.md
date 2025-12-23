# Scalability Options for LinkML Rules

## Problem Statement

Current approach works for 123 animal models (2,653 lines), but needs to scale to:
- 638 cell lines
- 194 antibodies
- 110 genetic reagents
- **Total: 1,069+ tools across all categories**

A single YAML file with 1,069 rules would be ~28,000 lines - likely too large for efficient loading and maintenance.

## Scalable Strategies

### Option 1: Split by Template (Recommended ⭐)

**Approach:** One schema per tool type, each with its own rules.

```
modules/Template/
├── AnimalIndividualTemplate.yaml     (123 rules, 2,653 lines)
├── CellLineTemplate.yaml             (638 rules, ~17,000 lines)
├── AntibodyTemplate.yaml             (194 rules, ~5,200 lines)
└── GeneticReagentTemplate.yaml       (110 rules, ~2,900 lines)
```

**Pros:**
- ✅ Natural separation by use case
- ✅ Each file is independently manageable
- ✅ Users only load the template they need
- ✅ No cross-template conflicts

**Cons:**
- ⚠️ Cell line file still large (~17K lines)

**Implementation:**
```bash
# Generate each template separately
python scripts/generate_animal_template_with_rules.py
python scripts/generate_cell_line_template_with_rules.py
python scripts/generate_antibody_template_with_rules.py
python scripts/generate_reagent_template_with_rules.py
```

---

### Option 2: Modular Rules with Imports

**Approach:** Split rules into separate files and import them.

```
modules/Template/
├── AnimalIndividualTemplate.yaml     (imports rule modules)
└── rules/
    ├── animal_models_0-50.yaml       (50 rules)
    ├── animal_models_51-100.yaml     (50 rules)
    └── animal_models_101-123.yaml    (23 rules)
```

**LinkML Schema:**
```yaml
# AnimalIndividualTemplate.yaml
imports:
  - rules/animal_models_0-50
  - rules/animal_models_51-100
  - rules/animal_models_101-123

classes:
  AnimalIndividualTemplate:
    slots: [...]
    # Rules loaded from imports
```

**Pros:**
- ✅ Keeps individual files small
- ✅ Can generate rules in parallel
- ✅ Easier to review changes (smaller diffs)

**Cons:**
- ⚠️ LinkML may not support importing rules (need to verify)
- ⚠️ More complex build process
- ⚠️ Still generates large merged schema

---

### Option 3: Selective Rules Generation

**Approach:** Only generate rules for high-value tools with complete metadata.

**Criteria for rule generation:**
1. Has RRID (authoritative identifier)
2. Has ≥5 metadata fields available
3. Used in ≥2 studies (popularity filter)

**Result:**
- Animal models: 123 → ~50 rules (only those with RRIDs)
- Cell lines: 638 → ~100 rules (only well-documented lines)
- Antibodies: 194 → ~50 rules (only with complete metadata)
- **Total: ~200 rules instead of 1,069**

**Remaining tools:** Still available as enum values, just without auto-fill rules

**Pros:**
- ✅ Dramatically reduces file size
- ✅ Focuses on most valuable use cases
- ✅ Still provides controlled vocabulary for all tools

**Cons:**
- ⚠️ Not all tools get auto-fill
- ⚠️ Need to define "high-value" criteria

**Implementation:**
```python
def should_generate_rule(model_name: str, model_data: Dict) -> bool:
    """Determine if a model warrants a rule."""
    # Must have RRID
    if 'RRID' not in model_data or not model_data['RRID']:
        return False

    # Must have at least 5 metadata fields
    field_count = sum(1 for v in model_data.values() if v)
    if field_count < 5:
        return False

    # Optional: Check usage frequency
    # if model_data.get('usage_count', 0) < 2:
    #     return False

    return True
```

---

### Option 4: Hybrid Enums + Rules

**Approach:** Combine benefits of both approaches.

**Structure:**
```yaml
classes:
  AnimalIndividualTemplate:
    slots:
      - modelSystemName  # Enum of ALL 123 models
      - species
      - genotype
      # ...

    rules:  # Only for top 20 most-used models
      - preconditions: ...
        postconditions: ...
```

**Plus external mappings:**
```json
// For programmatic auto-fill in DCA/Schematic
{
  "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)": {
    "species": "Mus musculus",
    "genotype": "C57BL/6"
  }
}
```

**Pros:**
- ✅ Small YAML file (only critical rules)
- ✅ Full enum for validation
- ✅ External mappings for all auto-fill
- ✅ Best of both worlds

**Cons:**
- ⚠️ Requires custom DCA integration
- ⚠️ Two sources of truth (rules + mappings)

---

### Option 5: Dynamic Schema Generation

**Approach:** Generate schema on-demand rather than pre-compiling.

**Architecture:**
```
User requests form
       ↓
DCA/Schematic queries: "Give me AnimalIndividualTemplate"
       ↓
Schema generator API:
  - Loads base template (slots only)
  - Queries tools database
  - Injects current rules
  - Returns complete schema
       ↓
User gets form with latest data
```

**Pros:**
- ✅ Always up-to-date
- ✅ No large static files
- ✅ Can filter rules by context

**Cons:**
- ❌ Requires API infrastructure
- ❌ Synapse may not support this
- ❌ More complex architecture

---

### Option 6: Tiered Rules System

**Approach:** Multiple levels of rules with different detail.

```yaml
rules:
  # Tier 1: Species-level rules (always apply)
  - preconditions:
      slot_conditions:
        species:
          equals_string: "Mus musculus"
    postconditions:
      slot_conditions:
        organism:
          equals_string: "Mus"

  # Tier 2: Common model rules (20 most used)
  - preconditions:
      slot_conditions:
        modelSystemName:
          equals_string: "B6.129(Cg)-Nf1tm1Par/J"
    postconditions:
      slot_conditions:
        species: {equals_string: "Mus musculus"}
        genotype: {equals_string: "C57BL/6"}
        # ... full metadata

  # Tier 3: Specific model rules (optional, loaded externally)
```

**Pros:**
- ✅ Hierarchical validation
- ✅ Core rules always present
- ✅ Detailed rules optional

**Cons:**
- ⚠️ Complex rule interactions
- ⚠️ Harder to maintain

---

## Recommended Hybrid Approach

Combine **Option 1** (split by template) + **Option 3** (selective rules):

### Implementation Plan

```python
#!/usr/bin/env python3
"""
Scalable rule generation with filtering.
"""

def generate_rules_with_filter(
    models: Dict[str, Dict],
    max_rules: int = 100,
    require_rrid: bool = True,
    min_fields: int = 5
):
    """
    Generate rules with quality filters.

    Args:
        models: All available models
        max_rules: Maximum number of rules to generate
        require_rrid: Only generate rules for models with RRID
        min_fields: Minimum metadata fields required
    """
    # Score each model
    scored_models = []
    for name, data in models.items():
        score = 0

        # RRID is high value
        if data.get('RRID'):
            score += 10

        # Count metadata fields
        field_count = sum(1 for v in data.values() if v)
        score += field_count

        # Could add: usage frequency, recency, etc.

        scored_models.append((score, name, data))

    # Sort by score and take top N
    scored_models.sort(reverse=True)
    top_models = scored_models[:max_rules]

    # Generate rules only for top models
    rules = []
    for score, name, data in top_models:
        if require_rrid and not data.get('RRID'):
            continue

        field_count = sum(1 for v in data.values() if v)
        if field_count < min_fields:
            continue

        rule = create_rule_for_model(name, data)
        if rule:
            rules.append(rule)

    return rules
```

### File Structure

```
modules/Template/
├── AnimalIndividualTemplate.yaml      # 50 top rules
├── CellLineTemplate.yaml              # 100 top rules
├── AntibodyTemplate.yaml              # 50 top rules
└── GeneticReagentTemplate.yaml        # 25 top rules

auto-generated/mappings/
├── animal_models_mappings.json        # All 123 models
├── cell_lines_mappings.json           # All 638 cell lines
└── ...                                # Full database preserved
```

### Benefits

✅ **Manageable file sizes** (50-100 rules per template)
✅ **Covers most use cases** (top models by quality/usage)
✅ **Full enum coverage** (all models still in vocabulary)
✅ **External mappings** (for programmatic access)
✅ **Flexible criteria** (can adjust thresholds)

---

## Performance Testing

Before committing to an approach, we should test:

### Test 1: Schema Loading Time
```python
import time
import yaml

# Test different file sizes
for num_rules in [50, 100, 200, 500, 1000]:
    start = time.time()
    schema = yaml.safe_load(generate_yaml_with_rules(num_rules))
    elapsed = time.time() - start
    print(f"{num_rules} rules: {elapsed:.3f}s")
```

### Test 2: JSON Schema Generation Time
```bash
time python utils/gen-json-schema-class.py --class AnimalIndividualTemplate
```

### Test 3: Synapse Upload/Load Time
```python
# Upload to Synapse and measure
syn.store(schema)
time_to_load = measure_form_load_time()
```

---

## Migration Path

### Phase 1: Prototype (Current ✅)
- [x] Generate AnimalIndividualTemplate with all 123 rules
- [x] Test basic functionality
- [x] Validate YAML structure
- [ ] Test with Synapse

### Phase 2: Optimize (If needed)
- [ ] Implement selective rule generation
- [ ] Set quality thresholds (RRID required, min 5 fields)
- [ ] Reduce to ~50 rules per template
- [ ] Compare performance

### Phase 3: Scale (Next templates)
- [ ] Generate CellLineTemplate with selective rules
- [ ] Generate AntibodyTemplate with selective rules
- [ ] Test multi-template system

### Phase 4: Productionize
- [ ] Add to GitHub Actions workflow
- [ ] Weekly regeneration from Synapse
- [ ] Curator review process
- [ ] Documentation for users

---

## Decision Matrix

| Approach | File Size | Completeness | Synapse Native | Complexity | Score |
|----------|-----------|--------------|----------------|------------|-------|
| Split by Template | Medium | High | Yes | Low | ⭐⭐⭐⭐ |
| Modular Imports | Small | High | Unknown | Medium | ⭐⭐⭐ |
| Selective Rules | Small | Medium | Yes | Low | ⭐⭐⭐⭐⭐ |
| Hybrid | Medium | High | Partial | Medium | ⭐⭐⭐⭐ |
| Dynamic | N/A | High | No | High | ⭐⭐ |
| Tiered | Medium | High | Unknown | High | ⭐⭐⭐ |

**Recommendation:** **Selective Rules** + **Split by Template**

---

## Next Steps

1. **Test current prototype with Synapse** (123 rules)
   - Measure loading performance
   - Verify rule behavior
   - Get feedback from curators

2. **If performance is acceptable:**
   - Generate CellLineTemplate with all 638 rules
   - Test that too
   - Compare performance

3. **If performance is poor:**
   - Implement selective rule generation
   - Use quality scoring (RRID, field count, usage)
   - Reduce to top 50-100 per template

4. **Productionize:**
   - Update generation scripts with filters
   - Document criteria for rule inclusion
   - Add monitoring for rule coverage

---

## Code Sketch: Selective Generation

```python
#!/usr/bin/env python3
"""
Enhanced script with selective rule generation.
"""

def generate_template_with_selective_rules(
    mappings_path: Path,
    output_path: Path,
    max_rules: int = 100,
    require_rrid: bool = True,
    min_fields: int = 5
):
    """Generate template with quality-filtered rules."""

    # Load all models
    models = load_models(mappings_path)
    print(f"Total models in database: {len(models)}")

    # Score and rank models
    ranked = rank_models_by_quality(models)

    # Select top N
    selected = select_top_models(ranked, max_rules, require_rrid, min_fields)
    print(f"Selected {len(selected)} models for rules")

    # Generate rules
    rules = [create_rule(model) for model in selected]

    # Create template with:
    # - All models in enum (for controlled vocabulary)
    # - Rules only for selected models (for auto-fill)
    template = create_template(
        all_models=models.keys(),
        rules=rules
    )

    # Write YAML
    write_yaml(template, output_path)

    # Generate report
    print_coverage_report(models, selected)

def rank_models_by_quality(models: Dict) -> List[Tuple]:
    """Rank models by quality score."""
    scored = []
    for name, data in models.items():
        score = calculate_quality_score(data)
        scored.append((score, name, data))
    return sorted(scored, reverse=True)

def calculate_quality_score(data: Dict) -> int:
    """Calculate quality score for a model."""
    score = 0

    # High-value fields
    if data.get('RRID'): score += 20
    if data.get('description'): score += 10
    if data.get('institution'): score += 5

    # Count all populated fields
    field_count = sum(1 for v in data.values() if v)
    score += field_count

    # Could add:
    # - Usage frequency from analytics
    # - Recency of last update
    # - Curator priority flags

    return score
```

---

## Conclusion

**Yes, this approach is feasible and scalable** with these strategies:

1. ✅ **Split by template** - Natural separation
2. ✅ **Selective rules** - Focus on high-quality tools
3. ✅ **Quality scoring** - Prioritize RRID, completeness, usage
4. ✅ **Keep full enums** - All tools available for selection
5. ✅ **External mappings** - Preserve full database for programmatic use

This gives us:
- **Small files** (~50-100 rules per template)
- **High coverage** (top 80% of use cases)
- **Fast loading** (reasonable file sizes)
- **Maintainable** (clear generation criteria)
- **Extensible** (easy to adjust thresholds)

The script we created (`generate_animal_template_with_rules.py`) can be enhanced with these filters, and we're ready to scale to all tool types.
