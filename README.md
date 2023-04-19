<img alt="GitHub release (latest by date)" src="https://img.shields.io/github/v/release/nf-osi/nf-metadata-dictionary?label=latest%20release&display_name=release&style=flat-square">  <img alt="GitHub Release Date" src="https://img.shields.io/github/release-date/nf-osi/nf-metadata-dictionary?style=flat-square&color=orange">  <img alt="GitHub" src="https://img.shields.io/github/license/nf-osi/nf-metadata-dictionary?style=flat-square&color=red">

#### Maintenance and Contribution

This section is for those who would like to be involved. 
We welcome contributions, whether you are a professional data modeler, clinician, or student in the NF community.
The purpose of the metadata dictionary is to have a set of standard terms that can be used to describe data. 

#### Steps to add an attribute to the Metadata Dictionary: 
1. Create a new [branch](https://github.com/nf-osi/nf-metadata-dictionary/branches) (example: patch/add-attribute)
2. Go to the csv file where the attribute belongs.  The components of the data model are organized in the folder [modules](https://github.com/nf-osi/nf-metadata-dictionary/tree/main/modules), e.g. in [modules/Assay](https://github.com/nf-osi/nf-metadata-dictionary/tree/main/modules/Assay) we have classes and  most pertinent to assays: Assay, Assay_Parameter, Platform,etc. as well as the relations csv called "annotationProperty". 
3. Add the attribute to the relevant csv file.  
4. Complete the columns for the attribute. At a minimum, add the following information - 
* `Attribute` : (REQUIRED) Name of the new concept.  
* `Description` : (REQUIRED) A description for the concept.  
* `Valid Values` : Only required if you are editing an `annotationProperty.csv` file, where you would be defining a new field (relation) and specifying what values are allowed to be used with this field (relation). For example, _tumorType_ is to valid values _{ Malignant Peripheral Sheath Tumor, Schwannoma, ... }_ as _eats_ is to valid values _{ pizza, sandwich, egg, ... }_.    
* `Source` : Preferably a URI to an ontology source term.
If you need help, you can do a pull request and the maintainer will help fill out the rest.  
4. If you are adding an attribute that is a valid value for another attribute, navigate to that csv file and add the term.
5. Create a pull request (PR) and add @allaway or @anngvu as a reviewer. Creating the PR will perform an action to updae the [NF.csv](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.csv) file and the [NF.jsonld](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.jsonld) from the modules folder. **You do not need to edit the `NF.csv` or `NF.jsonld` directly because it will be done automatically**
7. Make any neccessary changes after the review from an outside person, and then merge to the main branch. 
8. Draft a versioned release [here](https://github.com/nf-osi/nf-metadata-dictionary/releases).
9. Name the release with the the convention MAJOR.MINOR.PATCH. These releases start at v1.0.0. Versioning is roughly following semver.org concepts where: 

* MAJOR: *In-use* parent attributes are deleted from dictionary or modified, or in-use child attributes are modified in a non-backwards compatible way    (e.g. `Neurofibromatosis 1` changed to `Neurofibromatosis type 1`). 
* MINOR: Concepts/parent attributes are added. 
* PATCH: Child attributes are added, or *unused* child/parent attributes are deleted/modified, or definitions/`comments` are added/modified, or `validation rules` are modified in a backwards compatible way. 

9. The term is now added to the [metadata dictionary](https://nf-osi.github.io/nf-metadata-dictionary) and is accessible in templates used in the data curator app.

#### Further Information

#### Building Locally
For building locally, you will need to install the [schematic](https://github.com/Sage-Bionetworks/schematic) package. 
After adding a term, you can test whether the model "builds" by running `make CSV=NF.csv`.
But you do not have to build locally as we also have a GitHub Action workflow that will build any changes in `Modules/**` (this makes it easier for one-off contributions).

### Browse the metadata dictionary

You can browse the metadata dictionary here: https://nf-osi.github.io/nf-metadata-dictionary/.
To see (unversioned) schema history prior to v1.0.0, please view the history in the https://github.com/nf-osi/NF_data_curator repository. 

## Help

To contribute less directly or for other concerns, please create an issue at https://github.com/nf-osi/nf-metadata-dictionary/issues.

### License

The "collection" of metadata terms in this repository is made available under a CC0 license. The individual terms and their definitions may be subject to other (permissive) licenses, please see the source for each metadata term for details. 
