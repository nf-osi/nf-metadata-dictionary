<img alt="GitHub release (latest by date)" src="https://img.shields.io/github/v/release/nf-osi/nf-metadata-dictionary?label=latest%20release&display_name=release&style=flat-square">  <img alt="GitHub Release Date" src="https://img.shields.io/github/release-date/nf-osi/nf-metadata-dictionary?style=flat-square&color=orange">  <img alt="GitHub" src="https://img.shields.io/github/license/nf-osi/nf-metadata-dictionary?style=flat-square&color=red">


# nf-metadata-dictionary
Versioned releases of the JSON-LD-encoded NF Metadata Dictionary. 

These releases start at v1.0.0. To see (unversioned) schema history prior to v1.0.0, please view the history in the https://github.com/nf-osi/NF_data_curator repository. 

Versioning (MAJOR.MINOR.PATCH) is roughly following semver.org where: 

MAJOR: *In-use* parent attributes are deleted from dictionary or modified, or in-use child attributes are modified in a non-backwards compatible way (e.g. `Neurofibromatosis 1` changed to `Neurofibromatosis type 1`)
MINOR: Concepts/parent attributes are added. 
PATCH: Child attributes are added, or *unused* child/parent attributes are deleted, or definititions/`comments` are added/modified. 

## Browse the metadata dictionary

You can browse the metadata dictionary here: https://nf-osi.github.io/nf-metadata-dictionary/.
