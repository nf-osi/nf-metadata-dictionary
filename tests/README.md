## Test documentation

This describes the testing framework for the data model. 
The test suite is organized by functionality: 
- Test GENERATION of templates
- Test VALIDATION of manifests against templates
- Test SUBMISSION of manifests

Tests are *mostly* self-contained (don't depend on output from other tests) and should be run in their respective directory.
Exceptions and details are noted in the following dedicated sections.

### Test suite

#### Test GENERATION of templates

> [!NOTE]
> This can be run independently, i.e. it *does not* on any other tests here (though it does depend on the JSON-LD build).

This means means checking expectations that:
- [x] Templates can be generated at all with the version of `schematic` used, for the current JSON-LD data model. 
- [x] Templates look as expected when generated:
    - As a basic blank template not referring to any specific files
    - As a template instance with unannotated data filenames filled in
    - As a template for data files with *existing* annotations pulled in,
        - where existing annotations are compatible
        - where existing annotations are incompatible (schema changes have happened in-between)

At the most basic template generation mode, failures with a given version of `schematic` could mean:
- Version of `schematic` is too old and doesn't support whatever new validation rule/feature used in the model. This gives us information on the minimum compatible version.
- Version of `schematic` is too new and contains *breaking changes* that won't work with the current data model.  
- There's a problem with the data model such as a missing entity. For example, if a template uses a property (key) but that property is undefined in the data model so the schematic will complain at template generation time. 

At a more complicated template generation mode (with existing data involved), failures could mean:
- The template has been updated in a way that is not compatible with past versions/hard to handle. That means that a contributor trying to update their data with this new template will run into an error as well.
- Edge cases that's hard to handle within data model itself. Example: data has been annotated outside of DCA and doesn't conform to a template so schematic is confused when generating a template. 

##### Test fixtures

To test **basic** generation we need:
- the data model
- `config.yml` because schematic needs it
- `creds.json` API service credentials to make GSheets
- `config.json` matrix of templates to generate -- we actually just download `www/config.json` from DCA/staging as part of test script, so this ensures any templates expected to be used are tested

To test **advanced** generation as described above we additionally need:
- files with (good and bad) annotations on Synapse

##### Example run

- (in `tests/generate/`) `./basic_templates.sh` (generate basic blank GoogleSheets templates)

#### Test VALIDATION of manifests against their templates

> [!NOTE]
> This can be run independently, i.e. it *does not* depend on test GENERATION.

> [!TIP]
> The test script should match the parameters used by your DCA config.
> The script included here may not match your DCC's configuration, modify as needed if reusing.
> For example, some DCCs use Great Expectations rules, some don't, and this is controlled by the `-rr` flag. 

Question: Why do testing in addition to [the tests](https://github.com/Sage-Bionetworks/schematic/tree/develop/tests/data/mock_manifests) run by `schematic`?  
Answer: We sometimes have issues that are not covered by those tests or that we want to check specifically in the context of our own templates. 
Also, if there are unintuitive or unclear validation behaviors, it's a good idea to just create a mock manifest that captures that so you have it documented and validated how something works.

This means checking expectations that:
- [x] Manifest data that should pass are indeed passed by `schematic`. Example issue: https://github.com/Sage-Bionetworks/schematic/issues/732. Issues in this case lead to a poor experience for data contributors, who wouldn't appreciate spurious validation errors. 
- [x] Manifest data that should fail are indeed caught by `schematic`. Issues in this case lead to letting bad data pass and are arguably worse.  

##### Test fixtures 

To test validation we need:
- the data model 
- `config.yml` because schematic needs it
- good and bad manifests to test against some template(s) -- currently we use `GenomicsAssayTemplate` because it is heavily used and constitutes a large number of the most common properties/rules
- a `config.json` that basically describes the test matrix of good and bad manifests, their validation template, and expectations

##### Example run

- (in `/tests/validate/`) run `./run_config.sh`

##### Future generative data for testing vs using manually created data

Not to be confused with test generation section above, generative testing means generating manifest data for testing, similar to the idea of "synthetic data". Currently the "clean and dirty" manifests are created manually -- which can be a lot of work to have to sit down and think of all the weird things and how they should be handled by schematic validation. 

#### Test SUBMISSION of manifests

> [!NOTE]
> This *does* depend on the VALIDATION test suite being run, because only passing manifests from that will be submitted.  
Currently, we have partial implementation as seen in the checked features below.

This means checking that:
- [x] Valid manifests can be submitted at all. There have been cases where valid manifests are validated OK but unable to be submitted. 
- [ ] Manifest data are transferred as expected to Synapse (e.g. no weird conversions of types or truncation of data). This is the most complicated functionality across the test suite and requires querying the data that have been transferred to Synapse for comparison. Example issues: 
  - Integers are uploaded as doubles https://github.com/Sage-Bionetworks/schematic/issues/664
  - Blank values in the manifest become "NA" -- https://github.com/Sage-Bionetworks/schematic/issues/733
  - "NA" string value become `null` even though we may want to preserve "NA" -- https://github.com/Sage-Bionetworks/schematic/issues/821 + [internal thread](https://sagebionetworks.slack.com/archives/C01ANC02U59/p1681769606510569?thread_ts=1681769370.017039&cid=C01ANC02U59)

The test script functionality:
- Given valid `.csv` manifest(s), create entities in the manifest, and then update the manifest with the `entityId`s to test submit via schematic, then cleans up (deletes) mock entities.
- (TODO) After submission (if submission is successful), pull annotations from the entities and does expectation checks on each key-value.

##### Test fixtures

To test submission we need:
- valid manifest(s)  -- these are reused from the VALIDATION fixtures.
- a `config.json` that tells which dev/playground project to use, etc.

### General Testing TODO Ideas and Other Tips

- Testing can transition to using the schematic API service once it's ready (especially for template generation).
- How test scripts can be generalized/reused for other projects
- Main script to run through test suite in sequence 
