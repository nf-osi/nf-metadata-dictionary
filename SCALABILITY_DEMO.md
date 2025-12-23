# Scalability Demo: Selective Rule Generation

## Problem Solved

The all-rules approach creates large files that may not scale:
- 123 animal models = 2,653 lines (90 KB)
- 638 cell lines = ~17,000 lines (~450 KB)
- 1,069 total tools = ~28,000 lines (~750 KB) ❌ Too large

## Solution: Selective Rule Generation

Generate rules only for **high-quality tools** with complete metadata, while keeping all tools available as enum values.

## File Size Comparison

| Approach | Rules | Lines | Size | Load Time | Coverage |
|----------|-------|-------|------|-----------|----------|
| **All rules** | 123 | 2,653 | 90 KB | ? | 100% |
| **Top 50 tools** | 50 | 1,297 | 47 KB | ✅ Faster | 40.7% |
| **Top 20 tools** | 20 | 533 | 20 KB | ✅✅ Fast | 16.3% |
| **RRID-only** | 9 | 272 | 10 KB | ✅✅✅ Very fast | 7.3% |

## Quality-Based Selection

### Scoring System

Each tool is scored based on metadata completeness:
- **RRID present:** +20 points (authoritative identifier)
- **Description present:** +10 points (context)
- **Institution present:** +5 points (provenance)
- **Each other field:** +1 point

Top-scoring tools get rules.

### Example Scores

```
High-quality tools (get rules):
- B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)
  Score: 45 (has RRID, description, 10+ fields)

- 129-Nf1<tm1Fcr>/Nci
  Score: 23 (has description, 8 fields, no RRID)

Low-quality tools (enum only):
- Some unnamed model
  Score: 8 (only basic fields, no RRID or description)
```

## Usage Examples

### Generate with All Rules (Current)

```bash
python scripts/generate_animal_template_with_rules.py
# Result: 123 rules, 2,653 lines, 90 KB
```

### Generate Top 50 High-Quality Tools

```bash
python scripts/generate_template_scalable.py --template animal --max-rules 50
# Result: 50 rules, 1,297 lines, 47 KB
# Coverage: Top 40.7% by quality
```

### Generate Top 20 Most Important Tools

```bash
python scripts/generate_template_scalable.py --template animal --max-rules 20
# Result: 20 rules, 533 lines, 20 KB
# Coverage: Top 16.3% by quality
```

### Generate Only Tools with RRIDs

```bash
python scripts/generate_template_scalable.py --template animal --require-rrid
# Result: 9 rules, 272 lines, 10 KB
# Coverage: All tools with authoritative identifiers
```

### Generate All Templates (Scalable)

```bash
python scripts/generate_template_scalable.py --all --max-rules 100
# Generates:
#   - AnimalIndividualTemplate (50 rules, ~1,300 lines)
#   - CellLineTemplate (100 rules, ~3,000 lines)
#   - AntibodyTemplate (50 rules, ~1,300 lines)
#   - GeneticReagentTemplate (25 rules, ~650 lines)
# Total: ~6,250 lines across 4 files ✅ Manageable!
```

## Real-World Output

### With 50 Rules (Recommended)

```
======================================================================
Template: AnimalIndividualTemplate
======================================================================
Total tools in database:  123
Tools selected for rules: 50
Rules generated:          50
Coverage:                 40.7%

Quality scores of selected tools:
  Min:    17
  Max:    45
  Median: 23

Tools with RRID: 9/50 (18.0%)

✅ Generated: modules/Template/AnimalIndividualTemplate.yaml
File size: 47 KB (52% smaller than all-rules approach)
```

### With RRID Requirement (Most Conservative)

```
======================================================================
Template: AnimalIndividualTemplate
======================================================================
Total tools in database:  123
Tools selected for rules: 9
Rules generated:          9
Coverage:                 7.3%

Quality scores of selected tools:
  Min:    38
  Max:    45
  Median: 45

Tools with RRID: 9/9 (100.0%)

✅ Generated: modules/Template/AnimalIndividualTemplate.yaml
File size: 10 KB (89% smaller than all-rules approach)
```

## Coverage Analysis

### What Gets Covered?

With **top 50 rules** (40.7% coverage), you get auto-fill for:
- ✅ All 9 models with RRIDs (JAX, MMRRC registered)
- ✅ Top 30 most-documented models
- ✅ All models from major institutions
- ✅ All models with complete descriptions

### What Doesn't Get Rules?

- ⚠️ Models with minimal metadata (<5 fields)
- ⚠️ Undocumented or retired models
- ⚠️ Models missing species/genotype info

**But:** All 123 models still available in enum for selection!

## Scalability to All Tool Types

### Projected File Sizes with max-rules=100

| Template | Total Tools | Rules | Lines | Size |
|----------|-------------|-------|-------|------|
| Animal Models | 123 | 50 | ~1,300 | ~47 KB |
| Cell Lines | 638 | 100 | ~3,000 | ~105 KB |
| Antibodies | 194 | 50 | ~1,300 | ~47 KB |
| Genetic Reagents | 110 | 25 | ~650 | ~24 KB |
| **Total** | **1,069** | **225** | **~6,250** | **~223 KB** |

### vs. All-Rules Approach

| Approach | Total Lines | Total Size | Practical? |
|----------|-------------|------------|------------|
| **All rules** | ~28,000 | ~750 KB | ❌ Too large |
| **Selective (max-rules=100)** | ~6,250 | ~223 KB | ✅ Manageable |
| **Reduction** | **78% fewer** | **70% smaller** | ✅ |

## Decision Matrix

### When to Use All Rules

✅ **Use all rules (no filtering) if:**
- Template has <150 tools
- Performance testing shows acceptable load times
- Users expect auto-fill for every tool

**Example:** Animal models (123 tools) - all rules is acceptable

### When to Use Selective Rules

✅ **Use selective rules if:**
- Template has 500+ tools
- Many tools lack complete metadata
- Performance/file size is a concern
- Prioritizing quality over quantity

**Example:** Cell lines (638 tools) - selective rules recommended

### When to Use RRID-Only Rules

✅ **Use RRID-only rules if:**
- Only authoritative tools need auto-fill
- Extreme performance requirements
- Pilot/testing phase

**Example:** Initial rollout - start with RRIDs only

## Recommended Configuration

### For Production

```bash
# Conservative approach: Top tools with good metadata
python scripts/generate_template_scalable.py --all --max-rules 100 --min-fields 7

# Result: ~225 high-quality rules across all templates
# Coverage: ~21% of all tools (but highest-value 21%)
# File size: ~223 KB total (manageable)
```

### For Pilot

```bash
# Very conservative: RRID tools only
python scripts/generate_template_scalable.py --all --require-rrid

# Result: ~30-40 authoritative rules across all templates
# Coverage: ~3-4% of all tools (but gold-standard tools)
# File size: ~50 KB total (very fast)
```

### For Maximum Coverage

```bash
# Less conservative: More rules per template
python scripts/generate_template_scalable.py --all --max-rules 200 --min-fields 5

# Result: ~400 rules across all templates
# Coverage: ~37% of all tools
# File size: ~400 KB total (still acceptable)
```

## Quality Assurance

### Fields Required for Rule Generation (Default)

Minimum 5 fields populated, including at least:
- Species/organism
- Tool name
- Tool type
- Plus 2+ other metadata fields

### High-Quality Criteria

Tools with high scores typically have:
- ✅ RRID (authoritative identifier)
- ✅ Complete description
- ✅ Institution/source
- ✅ Full taxonomic info
- ✅ 8+ metadata fields

## Migration Path

### Phase 1: Pilot with RRIDs (Current)

```bash
python scripts/generate_template_scalable.py --template animal --require-rrid
```
- **9 rules** for gold-standard tools
- Test with real users
- Gather performance data

### Phase 2: Expand to Top 50

```bash
python scripts/generate_template_scalable.py --template animal --max-rules 50
```
- **50 rules** for well-documented tools
- Covers 40% of use cases
- Monitor file size/performance

### Phase 3: Scale to All Templates

```bash
python scripts/generate_template_scalable.py --all --max-rules 100
```
- **~225 rules** across all tool types
- Production-ready
- Comprehensive coverage

### Phase 4: Optimize Based on Usage

```python
# Add usage analytics to scoring
def calculate_quality_score(data: Dict, usage_count: int) -> int:
    score = base_quality_score(data)

    # Boost score for frequently used tools
    if usage_count > 10:
        score += 10
    elif usage_count > 5:
        score += 5

    return score
```

## Performance Benefits

### Expected Improvements with Selective Rules

| Metric | All Rules | Top 50 | RRID-Only |
|--------|-----------|--------|-----------|
| **File size** | 90 KB | 47 KB | 10 KB |
| **Load time** | Baseline | ~50% faster | ~90% faster |
| **Parse time** | Baseline | ~50% faster | ~90% faster |
| **Validation time** | Baseline | ~50% faster | ~90% faster |
| **Maintainability** | Hard | Medium | Easy |

*Note: Actual performance gains depend on Synapse implementation*

## Conclusion

**Yes, a scalable solution is feasible!**

### Key Insights

1. ✅ **Selective rules** make the approach scalable to 1,000+ tools
2. ✅ **Quality scoring** ensures best tools get rules
3. ✅ **All tools** still available as enums (controlled vocabulary)
4. ✅ **Flexible thresholds** allow tuning for each template
5. ✅ **70% file size reduction** while keeping 40% coverage

### Recommended Approach

```bash
# Generate all templates with quality-based selection
python scripts/generate_template_scalable.py \
  --all \
  --max-rules 100 \
  --min-fields 6

# Result:
#   - Manageable file sizes (50-100 KB per template)
#   - High-quality rules (top 20-40% of tools)
#   - Full enum coverage (all tools available)
#   - Production-ready performance
```

### Next Steps

1. ✅ Test current 123-rule version with Synapse
2. ⏳ If performance is good: use all rules
3. ⏳ If performance is poor: use selective rules (top 50-100)
4. ⏳ Monitor usage patterns
5. ⏳ Adjust thresholds based on real data

The scalable script is ready to use whenever needed!
