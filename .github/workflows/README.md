# GitHub Workflows

This directory contains automated workflows for maintaining the NF metadata dictionary.

## Update NF Tools Central Links

**File:** `update-tool-links.yml`

### Purpose

Automatically updates `see_also` links in schema enum values to point to NF Tools Central detail pages. This allows the webdev team to access resource detail page URLs directly from the schema without needing to call a REST API.

### Schedule

- **Automatic:** Every Monday at 10:00 AM UTC
- **Manual:** Can be triggered via GitHub Actions UI

### What It Does

1. Queries syn51730943 (NF Research Tools Central) for latest resource data
2. Updates `see_also` links in:
   - `modules/Sample/CellLineModel.yaml`
   - `modules/Sample/AnimalModel.yaml`
3. Rebuilds data model artifacts:
   - `dist/NF.yaml`
   - `NF.jsonld`
4. Creates a pull request if changes are detected

### Example Update

```yaml
# Before
"JH-2-002":
  description: "Collected during surgical resection from patients with NF1-MPNST"

# After
"JH-2-002":
  description: "Collected during surgical resection from patients with NF1-MPNST"
  see_also:
    - https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de
```

### Manual Trigger

1. Go to GitHub repository
2. Click `Actions` tab
3. Select `Update NF Tools Central Links` workflow
4. Click `Run workflow` button
5. Wait for workflow to complete
6. Review and merge the generated PR

### Required Secrets

- **NF_SERVICE_GIT_TOKEN**: GitHub token with write access (for creating PRs)
- **SYNAPSE_AUTH_TOKEN**: (Optional) Synapse authentication token
  - syn51730943 is open access, so this is only needed if anonymous access fails

### Related Files

- **Script:** `scripts/add_tool_links.py`
- **Documentation:** `scripts/README.md`
- **Related PR:** #780 (tooltip/reference service implementation)

### Workflow Steps

1. **Checkout repository** - Fetches latest code
2. **Set up Python** - Installs Python 3.10
3. **Install dependencies** - Installs synapseclient, pandas, pyyaml
4. **Add tool links** - Runs `add_tool_links.py` to update schemas
5. **Check for changes** - Detects if any files were modified
6. **Show diff summary** - Displays changes in workflow summary
7. **Rebuild artifacts** - Regenerates NF.yaml and NF.jsonld
8. **Create PR** - Creates pull request with updates (if changes detected)

### Generated PR Details

- **Title:** `Update NF Tools Central Links - YYYY-MM-DD`
- **Branch:** `update/tool-links-YYYYMMDD`
- **Labels:** `automated`, `tool-links`, `schema-update`
- **Status:** Ready for review (not draft)

### Benefits

- ✅ **No REST API needed** - Links embedded directly in schema
- ✅ **Always up-to-date** - Weekly automated synchronization
- ✅ **Full visibility** - PRs show exactly what changed
- ✅ **Easy review** - Diff summary in PR description
- ✅ **Zero maintenance** - Runs automatically

### When Changes Are Made

The workflow creates a PR when:
- New resources are added to syn51730943
- Resource IDs change in syn51730943
- Existing enum values gain links for the first time

### When No Changes Are Made

The workflow completes successfully but doesn't create a PR when:
- All enum values already have correct links
- No new resources have been added
- Resource IDs haven't changed

Check the workflow run summary to see the status.

## Integration with Other Workflows

This workflow is designed to run after the `weekly-model-system-sync.yml` workflow:

1. **9:00 AM UTC** - Model system sync updates enum values
2. **10:00 AM UTC** - Tool links workflow adds URLs to those values

This ensures that new resources added by the model system sync immediately get their detail page links.

## Troubleshooting

### Workflow fails with "Access denied"

syn51730943 is open access. If this error occurs:
1. Check that the table is still public
2. Add `SYNAPSE_AUTH_TOKEN` to repository secrets if needed

### Workflow creates empty PR

This shouldn't happen due to the `changes` check, but if it does:
1. Check the workflow logs
2. Verify `add_tool_links.py` is working correctly
3. Run the script locally to debug

### PR has unexpected changes

1. Review the diff in the PR
2. Check if syn51730943 data has changed
3. Verify the `resourceId` column mapping is correct

### Workflow doesn't run automatically

1. Check that the workflow file is on the default branch
2. Verify the cron schedule is correct
3. Check GitHub Actions settings are enabled for the repository

## Testing the Workflow

To test locally before the workflow runs:

```bash
# Install dependencies
pip install synapseclient pandas pyyaml

# Run the script
python scripts/add_tool_links.py --dry-run

# Check what would change
git diff modules/Sample/CellLineModel.yaml modules/Sample/AnimalModel.yaml
```

## Future Enhancements

- [ ] Add validation to verify links are accessible
- [ ] Automatic detection of resource ID column name
- [ ] Integration tests for workflow
- [ ] Slack/email notifications for PR creation
