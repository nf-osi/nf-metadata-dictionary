## Test documentation (WIP)

The testing framework for the data model is still in development; this documents some preliminary practices so far. 

### Test fixtures

#### Test manifest(s)

Ideally, make a test manifest .csv from some "representative" template, as in a popular template that has diverse properties and rules as constituents. 
Currently, the main test template is `GenomicsAssayTemplate` because it is heavily used and includes a large number of the most common properties/rules.  
If a change has been made that affects a production template, and it is not represented through a current test template, another template may need to be added. 

> **Note**
> Generating a .csv as below currently requires this [commit version](https://github.com/Sage-Bionetworks/schematic/commit/575387b69b2b10189cb53d43e9f1295096c72105) of schematic or more recent. If using an older version of schematic, you'll have to export as .csv manually after creating a blank GSheets manifest.

`schematic manifest -c config.yml get -dt GenomicsAssayTemplate -t "Test Manifest" --jsonld ./NF.jsonld --output_csv GenomicsAssayTemplate.csv`

The above is only necessary if the new data model specifies a template with different properties. 
Otherwise, use the existing version of `GenomicsAssayTemplate.csv` and edit values accordingly. 
If indeed migrating to a new template, rename the old one first to something like `old_GenomicsAssayTemplate.csv`, 
since many test values from the old version likely need to be transferred to the new version, after which the old test manifest can be removed. 

#### Test entities on Synapse

Entities to be mock-annotated in the test manifests should actually exist in [NF-test/annotations](https://www.synapse.org/#!Synapse:syn32530621).

#### Test script (WIP)

The test script will do several things:
- Submit the .csv manifest(s) via schematic. For reproducible local tests, a specific version of schematic needs to be available (see below for which versions should be configured).
- After submission (if submission is successful), it pulls annotations from the entities and does expectation checks. Expectation checks should be added to the script as needed. - Cleanup.

### Running tests (locally)

#### Schematic versions (WIP)

The test script uses the schematic CLI with specific flags that only work/makes sense for specific schematic versions. 


### TO-DOs

- Generate test files/values more programmatically.
- Document testing with specific versions of schematic. 

