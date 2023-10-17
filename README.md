<img alt="GitHub release (latest by date)" src="https://img.shields.io/github/v/release/nf-osi/nf-metadata-dictionary?label=latest%20release&display_name=release&style=flat-square">  <img alt="GitHub Release Date" src="https://img.shields.io/github/release-date/nf-osi/nf-metadata-dictionary?style=flat-square&color=orange">  <img alt="GitHub" src="https://img.shields.io/github/license/nf-osi/nf-metadata-dictionary?style=flat-square&color=red">

### Maintenance and Contribution

The purpose of the metadata dictionary is to provide a set of standard terms to describe data. Terms in the metadata dictionoary are used in the manifests within the [data curator app](https://dca.app.sagebionetworks.org/). 

This dictionary is maintained by the NF-Open Science Initative. We welcome contributions from community members, whether you are a professional data modeler, clinician, or student in the NF community.

## Maintenance and Contribution

The purpose of the metadata dictionary is to provide a set of standard terms to describe data. Terms in the metadata dictionary are used in the manifests within the [data curator app](https://dca.app.sagebionetworks.org/).

This dictionary is maintained by the NF-Open Science Initiative. We welcome contributions from community members, whether you are a professional data modeler, clinician, or student in the NF community.

### Steps to add an attribute to the Metadata Dictionary: 

1. Create a new [branch](https://github.com/nf-osi/nf-metadata-dictionary/branches) in the NF-metadata-dictionary repository. (example: patch/add-attribute)
2. Find the yaml file in the new branch where the attribute belongs. The components of the data model are organized in the folder labeled [modules](https://github.com/nf-osi/nf-metadata-dictionary/tree/main/modules).

3. Create a [pull request (PR)](https://github.com/nf-osi/nf-metadata-dictionary/compare) to merge the branch to "main". Add either @allaway, @anngvu, or @cconrad8 as a reviewer. Creating the PR will perform an action to update the [NF.csv](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.csv) file and the [NF.jsonld](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.jsonld) from the modules folder.

4. Make any necessary changes and then merge the new branch that was created to the main branch.
5. [Draft a versioned release here](https://github.com/nf-osi/nf-metadata-dictionary/releases).
6. Name the release with the convention MAJOR.MINOR.PATCH. These releases start at v1.0.0. Versioning is roughly following [semantic versioning](semver.org) concepts where: 

   - MAJOR: *In-use* parent attributes are deleted from dictionary or modified, or in-use child attributes are modified in a non-backwards compatible way (e.g. `Neurofibromatosis 1` changed to `Neurofibromatosis type 1`).
   - MINOR: Concepts/parent attributes are added.
   - PATCH: Child attributes are added, or *unused* child/parent attributes are deleted/modified, or definitions/`comments` are added/modified, or `validation rules` are modified in a backwards compatible way.

7. Navigate to data curator app [config file](https://github.com/Sage-Bionetworks/data_curator_config/blob/main/dcc_config.csv) to update the version. First, update the staging branch to test on the [staging app](https://dca-staging.app.sagebionetworks.org/). Then, checkout the main branch on your fork, update dcc_config.csv for NF so it matches the staging set up, then create a PR to main on the sage-bionetworks repo. Once merged, the changes should be visible on the data curator app.
8. **🎉 Congrats! The term is now added to the [metadata dictionary](https://nf-osi.github.io/nf-metadata-dictionary).**


### Further Information

#### Building Locally
To build locally, install the [schematic](https://github.com/Sage-Bionetworks/schematic) package.  

#### Help

For questions or to get help contributing a term, [please create an issue](https://github.com/nf-osi/nf-metadata-dictionary/issues).

#### License

The "collection" of metadata terms in this repository is made available under a CC0 license. The individual terms and their definitions may be subject to other (permissive) licenses, please see the source for each metadata term for details. 
