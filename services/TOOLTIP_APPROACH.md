# Tooltip/Reference Approach for Tool Metadata

## Overview

Instead of auto-filling tool metadata into form fields, display it as **reference information** in tooltips and detail views. This keeps schemas minimal while providing rich context.

## The Problem with Auto-fill

**Current auto-fill approach:**
```yaml
# Schema has many tool-derived fields
BiospecimenTemplate:
  slots:
    - resourceType
    - resourceName
    - species        # ← Auto-filled from tool DB
    - tissue         # ← Auto-filled from tool DB
    - organ          # ← Auto-filled from tool DB
    - diagnosis      # ← Auto-filled from tool DB
    - age            # ← Auto-filled from tool DB
    - RRID           # ← Auto-filled from tool DB
    # ... many more fields
```

**Problems:**
- ❌ Schema bloat (many redundant fields)
- ❌ Data duplication (same info in tool DB and metadata)
- ❌ Ambiguous source of truth
- ❌ Maintenance burden (field mappings)

## The Tooltip Solution

**Minimal schema:**
```yaml
BiospecimenTemplate:
  slots:
    - resourceType    # User selects: "Cell Line"
    - resourceName    # User selects: "JH-2-002"
    # That's it! No tool-derived fields
```

**Rich reference in UI:**
- Hover over selected tool → tooltip shows metadata
- Click on tool → detail panel opens
- Link to full tool page in database
- Button to suggest edits

## User Experience

### Step 1: Select Resource Type
```
┌─────────────────────────────────┐
│ Resource Type: [Cell Line ▼]   │
└─────────────────────────────────┘
```

### Step 2: Select Resource Name
```
┌─────────────────────────────────┐
│ Resource Type: Cell Line        │
│ Resource Name: [JH-2-002 ▼]     │
└─────────────────────────────────┘
```

### Step 3: Hover Shows Context
```
┌─────────────────────────────────┐
│ Resource Type: Cell Line        │
│ Resource Name: JH-2-002  ℹ️      │ ← Hover here
└─────────────────────────────────┘

        ↓ Shows tooltip

┌───────────────────────────────────────┐
│ 📊 JH-2-002 Cell Line                 │
├───────────────────────────────────────┤
│ Species: Homo sapiens                 │
│ Tissue: Brain                         │
│ Organ: Cerebrum                       │
│ Cell Type: Tumor                      │
│ Diagnosis: Glioblastoma multiforme    │
│ Age: 45 years                         │
│ Sex: Male                             │
│ RRID: CVCL_1234                       │
│ Institution: Johns Hopkins            │
│                                       │
│ 🔗 View full details in tool database│
│ ✏️ Suggest edits or additions        │
└───────────────────────────────────────┘
```

### Step 4: Click for Details
Opens detail panel or new tab with:
- Full tool metadata
- Related publications
- Usage history
- Edit suggestion form

## Implementation

### API Enhancement

Add tooltip endpoint to auto-fill service:

```python
@app.get("/api/v1/tooltip/{resource_type}/{resource_name}")
async def get_tooltip_data(resource_type: str, resource_name: str):
    """
    Get tooltip data for a resource.

    Returns:
        - display_name: Formatted name
        - metadata: Key-value pairs for tooltip
        - detail_url: Link to full details
        - edit_url: Link to suggest edits
    """
    # Query tool database
    tool = query_tool(resource_type, resource_name)

    return {
        "display_name": tool['name'],
        "type": resource_type,
        "metadata": {
            "Species": tool['species'],
            "Tissue": tool['tissue'],
            "Diagnosis": tool['diagnosis'],
            "Age": tool['age'],
            "RRID": tool['RRID'],
            # ... etc
        },
        "detail_url": f"https://synapse.org/tools/{tool['id']}",
        "edit_url": f"https://synapse.org/tools/{tool['id']}/edit"
    }
```

### UI Component (JavaScript)

```javascript
class ResourceTooltip {
  constructor(serviceUrl) {
    this.serviceUrl = serviceUrl;
  }

  async attachToField(fieldElement) {
    const resourceType = getResourceType();
    const resourceName = fieldElement.value;

    // Add info icon
    const icon = document.createElement('span');
    icon.innerHTML = 'ℹ️';
    icon.className = 'resource-info-icon';
    fieldElement.parentElement.appendChild(icon);

    // Fetch tooltip data
    const data = await this.fetchTooltipData(resourceType, resourceName);

    // Create tooltip
    const tooltip = this.createTooltip(data);

    // Show on hover
    icon.addEventListener('mouseenter', () => {
      this.showTooltip(tooltip, icon);
    });

    // Open details on click
    icon.addEventListener('click', () => {
      window.open(data.detail_url, '_blank');
    });
  }

  createTooltip(data) {
    const tooltip = document.createElement('div');
    tooltip.className = 'resource-tooltip';

    // Header
    const header = document.createElement('div');
    header.className = 'tooltip-header';
    header.innerHTML = `📊 ${data.display_name}`;
    tooltip.appendChild(header);

    // Metadata
    const metadata = document.createElement('div');
    metadata.className = 'tooltip-metadata';

    for (const [key, value] of Object.entries(data.metadata)) {
      if (value) {
        const row = document.createElement('div');
        row.innerHTML = `<strong>${key}:</strong> ${value}`;
        metadata.appendChild(row);
      }
    }
    tooltip.appendChild(metadata);

    // Actions
    const actions = document.createElement('div');
    actions.className = 'tooltip-actions';
    actions.innerHTML = `
      <a href="${data.detail_url}" target="_blank">
        🔗 View full details
      </a>
      <a href="${data.edit_url}" target="_blank">
        ✏️ Suggest edits
      </a>
    `;
    tooltip.appendChild(actions);

    return tooltip;
  }

  async fetchTooltipData(type, name) {
    const url = `${this.serviceUrl}/api/v1/tooltip/${type}/${name}`;
    const response = await fetch(url);
    return response.json();
  }
}

// Usage
const tooltips = new ResourceTooltip('https://autofill.nf-osi.org');
document.querySelectorAll('[data-field="resourceName"]').forEach(field => {
  tooltips.attachToField(field);
});
```

### Synapse Integration

#### Option 1: Custom Widget
Add to Synapse WebClient:

```java
// ResourceTooltipWidget.java
public class ResourceTooltipWidget extends Composite {
    private final AutofillService service;

    public void attachToField(TextBox resourceNameField) {
        // Add info icon
        InlineHTML icon = new InlineHTML("ℹ️");
        icon.addStyleName("resource-info-icon");

        // Show tooltip on hover
        icon.addMouseOverHandler(event -> {
            String resourceType = getResourceType();
            String resourceName = resourceNameField.getValue();

            service.getTooltipData(resourceType, resourceName,
                new AutofillCallback() {
                    @Override
                    public void onSuccess(TooltipData data) {
                        showTooltip(data, icon);
                    }
                });
        });

        // Open details on click
        icon.addClickHandler(event -> {
            String resourceType = getResourceType();
            String resourceName = resourceNameField.getValue();

            service.getTooltipData(resourceType, resourceName,
                new AutofillCallback() {
                    @Override
                    public void onSuccess(TooltipData data) {
                        Window.open(data.getDetailUrl(), "_blank", "");
                    }
                });
        });
    }
}
```

#### Option 2: Enhanced File View
Modify Synapse file view to show info icons for tool fields.

## Schema Changes

### Before (Auto-fill Approach)
```yaml
classes:
  BiospecimenTemplate:
    slots:
      - specimenID
      - resourceType
      - resourceName
      - species          # ← Remove (in tooltip instead)
      - tissue           # ← Remove
      - organ            # ← Remove
      - cellType         # ← Remove
      - diagnosis        # ← Remove
      - age              # ← Remove
      - sex              # ← Remove
      - RRID             # ← Remove
      - institution      # ← Remove
      # ... 20+ fields total
```

### After (Tooltip Approach)
```yaml
classes:
  BiospecimenTemplate:
    slots:
      - specimenID
      - resourceType     # Cell Line, Animal Model, etc.
      - resourceName     # JH-2-002, B6.129(Cg)-Nf1tm1Par/J, etc.
      # That's it! Only 3 fields
      # Tool metadata shown in tooltip, not stored
```

**Result:**
- 85% fewer fields in schema
- No data duplication
- Clear source of truth
- Better UX

## Tool Database Integration

### Detail Page
When user clicks "View full details":

```
https://synapse.org/tools/syn12345678

┌────────────────────────────────────────┐
│ JH-2-002 Cell Line                     │
├────────────────────────────────────────┤
│ Basic Information                      │
│   Name: JH-2-002                       │
│   Type: Cell Line                      │
│   RRID: CVCL_1234                      │
│   Institution: Johns Hopkins University│
│                                        │
│ Biological Properties                  │
│   Species: Homo sapiens                │
│   Tissue: Brain                        │
│   Organ: Cerebrum                      │
│   Cell Type: Tumor                     │
│   Diagnosis: Glioblastoma multiforme   │
│                                        │
│ Patient Information                    │
│   Age: 45 years                        │
│   Sex: Male                            │
│   Ethnicity: Caucasian                 │
│                                        │
│ Usage                                  │
│   Studies using this cell line: 12     │
│   Datasets: 45                         │
│   Publications: 8                      │
│                                        │
│ [✏️ Suggest Edits] [📋 Use in Study]  │
└────────────────────────────────────────┘
```

### Edit Suggestion Form
When user clicks "Suggest edits":

```
https://synapse.org/tools/syn12345678/edit

┌────────────────────────────────────────┐
│ Suggest Edits: JH-2-002               │
├────────────────────────────────────────┤
│ What would you like to change?        │
│                                        │
│ Field: [Select field ▼]               │
│                                        │
│ Current value: [Auto-filled]           │
│ Suggested value: [Your input]          │
│                                        │
│ Reason for change:                     │
│ [Text area]                            │
│                                        │
│ Supporting evidence (optional):        │
│ [URL or reference]                     │
│                                        │
│ [Submit Suggestion] [Cancel]           │
└────────────────────────────────────────┘
```

Suggestion goes to tool database curators for review.

## Benefits

### For Users
- ✅ **Cleaner forms** - Only fields they need to fill
- ✅ **Rich context** - See tool details without cluttering form
- ✅ **Easy reference** - Hover to check, click for more
- ✅ **Contribute back** - Suggest improvements to tool database

### For Curators
- ✅ **Less validation** - Tool metadata not duplicated
- ✅ **Single source** - Tool DB is authoritative
- ✅ **Quality control** - Community helps improve tool data
- ✅ **Cleaner data** - No conflicting metadata

### For Developers
- ✅ **Smaller schemas** - 85% fewer fields
- ✅ **Less complexity** - No field mapping maintenance
- ✅ **Separation of concerns** - Tool data stays in tool DB
- ✅ **Easier testing** - Simpler schemas to validate

## Migration Path

### Phase 1: Add Tooltip Support (Now)
1. Add `/api/v1/tooltip` endpoint to service
2. Create JavaScript tooltip component
3. Deploy alongside existing auto-fill
4. Test with users

### Phase 2: Update One Template (Next Month)
1. Choose pilot template (e.g., BiospecimenTemplate)
2. Remove tool-derived fields from schema
3. Add tooltip UI to curation grid
4. Gather feedback

### Phase 3: Rollout (Next Quarter)
1. Apply to all templates with tools
2. Deprecate auto-fill endpoints
3. Train users on new UX
4. Monitor adoption

### Phase 4: Tool DB Enhancement (Next Year)
1. Build tool detail pages
2. Add edit suggestion workflow
3. Curator review interface
4. Community contribution tracking

## Technical Specification

### API Endpoints

#### GET /api/v1/tooltip/{resource_type}/{resource_name}
Returns tooltip data for display.

**Response:**
```json
{
  "display_name": "JH-2-002",
  "type": "Cell Line",
  "metadata": {
    "Species": "Homo sapiens",
    "Tissue": "Brain",
    "Organ": "Cerebrum",
    "Cell Type": "Tumor",
    "Diagnosis": "Glioblastoma multiforme",
    "Age": "45 years",
    "Sex": "Male",
    "RRID": "CVCL_1234",
    "Institution": "Johns Hopkins University"
  },
  "detail_url": "https://synapse.org/tools/syn12345678",
  "edit_url": "https://synapse.org/tools/syn12345678/suggest-edit",
  "last_updated": "2025-12-22T10:30:00Z"
}
```

#### POST /api/v1/suggest-edit
Submit edit suggestion for tool metadata.

**Request:**
```json
{
  "resource_type": "Cell Line",
  "resource_name": "JH-2-002",
  "field": "Age",
  "current_value": "45 years",
  "suggested_value": "47 years",
  "reason": "Updated based on recent publication",
  "evidence": "https://pubmed.ncbi.nlm.nih.gov/12345678",
  "submitter_email": "user@example.com"
}
```

**Response:**
```json
{
  "suggestion_id": "edit_12345",
  "status": "pending_review",
  "message": "Thank you! Your suggestion has been submitted for curator review."
}
```

## CSS Styling

```css
/* Info icon next to field */
.resource-info-icon {
  cursor: pointer;
  margin-left: 5px;
  opacity: 0.7;
  transition: opacity 0.2s;
}

.resource-info-icon:hover {
  opacity: 1;
}

/* Tooltip popup */
.resource-tooltip {
  position: absolute;
  background: white;
  border: 1px solid #ccc;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  padding: 16px;
  max-width: 400px;
  z-index: 1000;
}

.tooltip-header {
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #eee;
}

.tooltip-metadata {
  margin-bottom: 12px;
}

.tooltip-metadata > div {
  margin: 6px 0;
  font-size: 14px;
}

.tooltip-actions {
  padding-top: 8px;
  border-top: 1px solid #eee;
}

.tooltip-actions a {
  display: block;
  margin: 4px 0;
  color: #0066cc;
  text-decoration: none;
}

.tooltip-actions a:hover {
  text-decoration: underline;
}
```

## Comparison: Auto-fill vs Tooltip

| Aspect | Auto-fill | Tooltip |
|--------|-----------|---------|
| **Fields in schema** | 20+ | 3 |
| **Data duplication** | Yes | No |
| **Form clutter** | High | Low |
| **Source of truth** | Ambiguous | Clear |
| **User edits** | Difficult | Easy |
| **Maintenance** | High | Low |
| **Implementation** | Complex | Simple |

## Recommendation

**Use tooltip approach instead of auto-fill** because:

1. ✅ **Cleaner** - 85% fewer schema fields
2. ✅ **Correct** - Single source of truth
3. ✅ **Better UX** - Contextual reference vs cluttered form
4. ✅ **Maintainable** - No field mappings to maintain
5. ✅ **Collaborative** - Easy to suggest improvements

The auto-fill service we built can be easily adapted to serve tooltips instead.

## Next Steps

1. Add tooltip endpoint to service
2. Build JavaScript tooltip component
3. Test with one template
4. Gather feedback
5. Roll out to all templates
