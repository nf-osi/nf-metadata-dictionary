<img alt="GitHub release (latest by date)" src="https://img.shields.io/github/v/release/nf-osi/nf-metadata-dictionary?label=latest%20release&display_name=release&style=flat-square">  <img alt="GitHub Release Date" src="https://img.shields.io/github/release-date/nf-osi/nf-metadata-dictionary?style=flat-square&color=orange">  <img alt="GitHub" src="https://img.shields.io/github/license/nf-osi/nf-metadata-dictionary?style=flat-square&color=red">

### Maintenance and Contribution

The purpose of the data model is to provide a set of standard concepts and structure that help to describe and manage data. 
Terms in the metadata dictionary are used in the manifests within the [data curator app](https://dca.app.sagebionetworks.org/). 
This dictionary is maintained by the NF-Open Science Initative. We welcome contributions from community members, whether you are a professional data modeler, clinician, or student in the NF community.

### Data Model Framework

The data model is maintained as a subset of the YAML-based **Linked Data Modeling Language ([LinkML](https://linkml.io/linkml/))** that is compatible with our internal tool [schematic](https://github.com/sage-bionetworks/schematic). 
This subset of LinkML should be easy to get started with.

#### The 10-minute Intro

The data model primarily models different types of biological data and patients/samples and uses templates that collects information for these entities. 
(It may helpful to also read about [Entity-Relation Model](https://en.wikipedia.org/wiki/Entity%E2%80%93relationship_model).)

To do this the building blocks are:

| LinkML term        | Schematic Note | Other Note |
| ------------------ | -------------  |------------|
| Class              | Usually corresponds to "Component"; schematic uses definition to make a "manifest"                                  | Also known as "template"
| Slot               | Schematic calls these "attributes"; the range can be typical types (string, int, etc.) or enumerations (below) | Also known as "property"
| Enum (enumeration) | Schematic calls these "valid values"                                                                                | Also known as "controlled values"  

Classes depend on slots being defined, and some slots depend on enumerated values being defined. 
If a class uses a slot that is not defined, the model will error when trying to build; and same with a slot that uses an enumeration.
Slots can be reused across classes; and same with enumerations for slot. 
For example, `unit` can be reused across any class entities that needs to capture unit information.

#### Classes

Classes have slots (properties). 
All classes are grouped under `modules/Template`. 
Classes can be built upon, so subclasses inherit properties from a parent class. 

##### Example: Class

Here is an small-ish base class definition for a patient:

```
  PatientTemplate:
    is_a: Template
    description: >
      Template for collecting *minimal* individual-level patient data. 
    slots:
    - individualID
    - sex
    - age
    - ageUnit
    - species # should be constrained to human
    - diagnosis
    - nf1Genotype
    - nf2Genotype
    annotations:
      requiresComponent: ''
      required: false
```

#### Slots

Slots have a range, which can be a basic data type such as "string" and "integer", or a set of controlled values (see Enum). 
If the range of a slot is not explicit defined, it defaults to "string" (basically free text).
All slots are in the file `modules/props.yaml`. 

##### Example slots

```
slots:
  #...more above
  tissue:
    description: Association with some tissue (a mereologically maximal collection of cells that together perform physiological function).
    range: TissueEnum # Take a look at TissueEnum below
    required: false
  title:
    description: Title of a resource.
    meaning: https://www.w3.org/TR/vocab-dcat-3/#Property:resource_title
    required: true
  # ...more below
```

Here, `required` defines globally whether this slot *must* be filled out.

#### Enum

An enumeration is a set of controlled values. 
Enums are most of the files `modules`, everything except for what's in `Templates` and `props.yaml`.

##### Example: Tissue enumeration

```
enums:
  TissueEnum:
    permissible_values:
      cerebral cortex:
        description: The outer layer of the cerebrum composed of neurons and unmyelinated nerve fibers. It is responsible for memory, attention, consciousness and other higher levels of mental function.
        meaning: http://purl.obolibrary.org/obo/NCIT_C12443
      bone marrow:
        description: The soft, fatty, vascular tissue that fills most bone cavities and is the source of red blood cells and many white blood cells.
        meaning: http://purl.obolibrary.org/obo/BTO_0000141
     #...more below
```

##### Example: Boolean Enumeration (commonly reused) 

```
enums:
  BooleanEnum: 
    description: 'Boolean values as Yes/No enums'
    permissible_values:
      'Yes':
        description: 'True'
      'No':
        description: 'False'
```

#### General meta to describe classes, slots, and enums

Aside from meta specific to each type (class, slot, or enum) above, terms have common meta, where the most prominent are summarized here:

- `description`: Description to help understand the term.
- `meaning`: This is a highly recommended and should be an **ontology URI that the term maps to**.
- `source`: This can be used to supplement `meaning`, but it's most often used when an ontology URI does not exist.
  It provides a reference such as a publication. For example, a very novel assay might not have a real ontology concept yet but will likely be described in a paper.
- `notes`: Internal editor notes.


### Steps to add an attribute to the Metadata Dictionary: 

1. Create a new [branch](https://github.com/nf-osi/nf-metadata-dictionary/branches) in the NF-metadata-dictionary repository. (example: patch/add-attribute)
2. Find the yaml file in the new branch where the attribute belongs. The components of the data model are organized in the folder labeled [modules](https://github.com/nf-osi/nf-metadata-dictionary/tree/main/modules).

3. Create a [pull request (PR)](https://github.com/nf-osi/nf-metadata-dictionary/compare) to merge the branch to "main". Add either @allaway, @anngvu, or @cconrad8 as a reviewer. Creating the PR will:  
   i. Build the [NF.jsonld](https://github.com/nf-osi/nf-metadata-dictionary/blob/main/NF.jsonld) from the module source files. This is the format needed by schematic.
   **Therefore, you do not need to edit the `NF.jsonld` directly, because it will be done automatically by our service bot.**
   
   ii. If build succeeds, also run some tests to make sure all looks good/generate previews. After some minutes, a test report will appear in the PR that hopefully looks like this:
   
   <img width="464" alt="image" src="https://github.com/nf-osi/nf-metadata-dictionary/assets/32753274/067f65ff-e39d-4b45-abae-ef22cf7df5eb">
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
