<img alt="GitHub release (latest by date)" src="https://img.shields.io/github/v/release/nf-osi/nf-metadata-dictionary?label=latest%20release&display_name=release&style=flat-square">  <img alt="GitHub Release Date" src="https://img.shields.io/github/release-date/nf-osi/nf-metadata-dictionary?style=flat-square&color=orange">  <img alt="GitHub" src="https://img.shields.io/github/license/nf-osi/nf-metadata-dictionary?style=flat-square&color=red">

### Maintenance and Contribution

The purpose of the metadata dictionary is to provide a set of standard terms to describe data. Terms in the metadata dictionoary are used in the manifests within the [data curator app](https://sagebio.shinyapps.io/NF_data_curator/).
This dictionary is maintained by the NF-Open Science Initative. We welcome contributions from community members, whether you are a professional data modeler, clinician, or student in the NF community.

### Steps to add an attribute to the Metadata Dictionary: 
<ins>**Steps 1 - 6 are performed by a "contributor" (i.e. community member) or "maintainer" (i.e. NF-OSI)**</ins>

1. Create a new [branch](https://github.com/nf-osi/nf-metadata-dictionary/branches) in the NF-metadata-dictionary repository. (example: patch/add-attribute)
2. Find the csv file in the new branch where the attribute belongs.  The components of the data model are organized in the folder labled [modules](https://github.com/nf-osi/nf-metadata-dictionary/tree/main/modules).

_e.g. As shown below, in [modules/Assay](https://github.com/nf-osi/nf-metadata-dictionary/tree/main/modules/Assay) there are classes associated with assays: Assay, Assay_Parameter, Method, and Platform and the relations csv file, annotationProperty._

<img src="https://user-images.githubusercontent.com/114612268/233366709-d2bbc499-f734-4224-9862-abc92f18b236.png" alt="modules" width="400"/>

3. Add the attribute to the relevant csv file by either 1) <ins>↓</ins> downloading the csv file , editing in excel and reuploading or 2) editing the raw csv as shown below: 

<img src="https://user-images.githubusercontent.com/114612268/233368135-88b830b0-b8c6-42c5-ac2f-01cc2e5d1333.png" alt="raw csv" width="1000"/>

4. Complete the columns for the attribute and "commit changes" to the new branch. At a minimum, add **Attribute**, **Description**, **Valid Values** and **Source** - 
If you need help, the maintainer will help fill out the rest after you do a pull request.

 Attribute*** | Description*** | Valid Values | Source***
---|---|---|---
 Name of the new concept | A description for the concept.   | Only required if you are editing an annotationProperty.csv file, where you would be defining a new field (relation) and specifying what values are allowed to be used with this field (relation). For example, _tumorType_ is to valid values _{ Malignant Peripheral Sheath Tumor, Schwannoma, ... }_ as _eats_ is to valid values _{ pizza, sandwich, egg, ... }_.  | Preferably a URI to an ontology source term
 
*** = Required

5. Add the attribute under "Valid Values" for other attributes it pertains to. 
6. Create a [pull request (PR)](https://github.com/nf-osi/nf-metadata-dictionary/compare) to merge the branch to "main". Add either @allaway, @anngvu, or @cconrad8 as a reviewer. Creating the PR will perform an action to update the [NF.csv](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.csv) file and the [NF.jsonld](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.jsonld) from the modules folder. **Therefore, you do not need to edit the `NF.csv` or `NF.jsonld` directly because it will be done automatically**

<ins>**Steps 7-9 are performed only by the "maintainer"**</ins>

7. Make any neccessary changes and then merge the new branch that was created to the main branch. 
8. [Draft a versioned release here](https://github.com/nf-osi/nf-metadata-dictionary/releases).
9. Name the release with the the convention MAJOR.MINOR.PATCH. These releases start at v1.0.0. Versioning is roughly following [semantic versioning](semver.org) concepts where: 

* MAJOR: *In-use* parent attributes are deleted from dictionary or modified, or in-use child attributes are modified in a non-backwards compatible way    (e.g. `Neurofibromatosis 1` changed to `Neurofibromatosis type 1`). 
* MINOR: Concepts/parent attributes are added. 
* PATCH: Child attributes are added, or *unused* child/parent attributes are deleted/modified, or definitions/`comments` are added/modified, or `validation rules` are modified in a backwards compatible way. 

10. **🎉 Congrats! The term is now added to the [metadata dictionary](https://nf-osi.github.io/nf-metadata-dictionary).**

### Further Information

#### Building Locally
To build locally, install the [schematic](https://github.com/Sage-Bionetworks/schematic) package. 
Test whether the module "builds" by running **make CSV=NF.csv**. 

#### Help

For questions or to get help contributing a term, [please create an issue](https://github.com/nf-osi/nf-metadata-dictionary/issues).

#### License

The "collection" of metadata terms in this repository is made available under a CC0 license. The individual terms and their definitions may be subject to other (permissive) licenses, please see the source for each metadata term for details. 
