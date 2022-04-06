<img alt="GitHub release (latest by date)" src="https://img.shields.io/github/v/release/nf-osi/nf-metadata-dictionary?label=latest%20release&display_name=release&style=flat-square">  <img alt="GitHub Release Date" src="https://img.shields.io/github/release-date/nf-osi/nf-metadata-dictionary?style=flat-square&color=orange">  <img alt="GitHub" src="https://img.shields.io/github/license/nf-osi/nf-metadata-dictionary?style=flat-square&color=red">


## nf-metadata-dictionary
Versioned releases of the JSON-LD-encoded NF Metadata Dictionary. 

These releases start at v1.0.0. To see (unversioned) schema history prior to v1.0.0, please view the history in the https://github.com/nf-osi/NF_data_curator repository. 

Versioning (MAJOR.MINOR.PATCH) is roughly following semver.org concepts where: 

* MAJOR: *In-use* parent attributes are deleted from dictionary or modified, or in-use child attributes are modified in a non-backwards compatible way (e.g. `Neurofibromatosis 1` changed to `Neurofibromatosis type 1`). 
* MINOR: Concepts/parent attributes are added. 
* PATCH: Child attributes are added, or *unused* child/parent attributes are deleted/modified, or definitions/`comments` are added/modified, or `validation rules` are modified in a backwards compatible way. 

### Maintenance and Contribution

This section is for those who would like to be involved. 
We welcome contributions, whether you are a professional data modeler, clinician, or student in the NF community.

#### Editing

The components of the data model are organized in `modules/*`, e.g. in `modules/Assay` we have classes and relations most pertinent to assays: Assay, Assay_Parameter, Platform, annotationProperty (relations).
So if you wish to add an assay or platform, edit only the relevant file and make a pull request. 
**Do not edit `NF.csv` or `NF.jsonld` directly!**

For each .csv file, the most important columns are described below; most contributions will need to deal directly only with these, and in a PR a maintainer will help fill the rest. (For advanced contributions, you can DM one of the maintainers.)  

* `Attribute` : (REQUIRED) Name of the new concept.  
* `Description` : (REQUIRED) A description for the concept.  
* `Valid Values` : Only required if you are editing an `annotationProperty.csv` file, where you would be defining a new field (relation) and specifying what values are allowed to be used with this field (relation).  
For example, _tumorType_ is to valid values _{ Malignant Peripheral Sheath Tumor, Schwannoma, ... }_ as _eats_ is to valid values _{ pizza, sandwich, egg, ... }_.    
* `Source` : Preferably a URI to an ontology source term.

#### Building

"Building" will create the `NF.csv` file and the `NF.jsonld` from that.

For building locally, you will need to install the [schematic](https://github.com/Sage-Bionetworks/schematic) package. 
After adding a term, you can test whether the model "builds" by running `make CSV=NF.csv`.
But you do not have to build locally as we also have a GitHub Action workflow that will build any changes in `Modules/**` (this makes it easier for one-off contributions).

#### Merging

For any PRs, you can add as reviewer one of the maintainers, @allaway or @anngvu.

### Other

To contribute less directly or for other concerns, please create an issue at https://github.com/nf-osi/nf-metadata-dictionary/issues.

### Browse the metadata dictionary

You can browse the metadata dictionary here: https://nf-osi.github.io/nf-metadata-dictionary/.

### License

The "collection" of metadata terms in this repository is made available under a CC0 license. The individual terms and their definitions may be subject to other (permissive) licenses, please see the source for each metadata term for details. 
