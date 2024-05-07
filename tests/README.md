## Test documentation

This describes the testing framework for the data model. 
The test suite is organized by functionality: 
- Test GENERATION of templates
- Test VALIDATION of manifests against templates
- Test SUBMISSION of manifests

Tests are *mostly* self-contained (don't depend on output from other tests) and should be run in their respective directory;
the exceptions and details are in the following sections.

These correspond to [`schematic manifest get`](https://sage-schematic.readthedocs.io/en/develop/cli_reference.html#schematic-manifest-get), [`schematic model validate`](https://sage-schematic.readthedocs.io/en/develop/cli_reference.html#schematic-model-validate), and [`schematic model submit`](https://sage-schematic.readthedocs.io/en/develop/cli_reference.html#schematic-model-submit), respectively.
Tests are pretty self-contained (don't depend on output from other tests) and should be run in their respective directory.
Details are in the following dedicated sections.

### Test suite

#### Test GENERATION of manifest templates

> [!NOTE]
> This can be run independently, i.e. it *does not* on any other tests here (though it does depend on the JSON-LD build).

This means means checking expectations that:
- [x] Templates can be generated at all with the version of `schematic` used, for the current JSON-LD data model. 
- [x] Templates look as expected when generated for a new dataset of a particular data type (no existing annotations).
- [ ] Templates look as expected when generated for a dataset of a particular data type when pulling in existing annotations. 

At the most basic template generation mode, failures with a given version of `schematic` could mean:
- Version of `schematic` is too old and doesn't support whatever new validation rule syntax/feature used in the model. This gives us information on the minimum compatible version.
- Version of `schematic` is too new and contains *breaking changes* that won't work with the current data model.  
- There's a problem with the data model such as a missing entity. For example, if a template uses a property (key) but that property is undefined in the data model so the schematic will complain at template generation time. 

At a more complicated template generation mode (with existing data involved), failures could mean:
- The template has been updated in a way that is not compatible with past versions/hard to handle. That means that a contributor trying to update their data with this new template will run into an error as well.
- Edge cases that's hard to handle within data model itself. Example: data has been annotated outside of DCA and doesn't conform to a template so schematic is confused when generating a template. 

###### Note on "advanced" manifest template generation

Manifests templates can be generated with values filled in from previous submissions, instead of a blank template with just entity ids/names. 
However, this mode is not currently tested. It is also more DCC-variable, because existing values can be sourced from annotations, tables, or files as several different sources of truth.

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
> The test script should match the parameters used by your [DCA config](https://github.com/Sage-Bionetworks/data_curator_config/).
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
- [x] Valid manifests can be submitted at all. There have been cases where valid manifests are validated OK but unable to be submitted. Sometimes it could be a cloud service issue when using the public schematic API; testing submission with the pure client (without the cloud layer) helps better distinguish where the error is coming from. Example issues:
      - https://github.com/Sage-Bionetworks/data_curator/issues/393
      - https://sagebionetworks.jira.com/browse/FDS-1968
- [ ] Manifest data are transferred as expected to Synapse (e.g. no weird conversions of types or truncation of data).
      This is the most complicated functionality across the test suite and requires querying the data that have been transferred to Synapse for comparison. Example issues: 
  - Integers are uploaded as doubles https://github.com/Sage-Bionetworks/schematic/issues/664
  - Blank values in the manifest become "NA" -- https://github.com/Sage-Bionetworks/schematic/issues/733
  - "NA" string value become `null` even though we may want to preserve "NA" -- https://github.com/Sage-Bionetworks/schematic/issues/821 + [internal thread](https://sagebionetworks.slack.com/archives/C01ANC02U59/p1681769606510569?thread_ts=1681769370.017039&cid=C01ANC02U59)

The test script functionality:
- Given valid `.csv` manifest(s), create entities in the manifest, and then update the manifest with the `entityId`s to test submit via schematic, then cleans up (deletes) mock entities.
- (TODO) After submission (if submission is successful), pull annotations from the entities and does expectation checks on each key-value.

##### Test fixtures

To test submission we need:
- valid manifest(s)  -- these are reused from VALIDATION fixtures.
- a `config.json` to specify Synapse test project and paths to validation fixtures

### General Testing TODO Ideas and Other Tips

- Testing can transition to using the schematic API service once it's ready (especially for template generation).
- How test scripts can be generalized/reused for other projects
- Main script to run through test suite in sequence 
