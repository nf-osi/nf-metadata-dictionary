# Contribution Guide

_This guide was adopted and modified from the Sage-Bionetworks/synapseAnnotations guide._ 

Welcome! This project is for managing annotations and controlled vocabularies for use in the NF-OSI. 

## Modifying the dictionary

If you are adding a value to an existing term:

0) If you are not comfortable using GitHub, or would prefer that we make a change on your behalf, please go to the [Issues](https://github.com/nf-osi/nf-metadata-dictionary/issues) tab and file a new issue, selecting the appropriate issue template as needed.

Otherwise...
1) Create a new branch or fork to make your changes. 
2) Edit the NF.csv file to make your proposed addition, removal, or modification.
3) Push the change to your branch. A GitHub Action will run to convert the csv file to update the NF.jsonld file with your changes. _Your change should be as atomic as possible - e.g., don't lump together many unrelated changes into a single issue or pull request. You may be requested to split them out._
4) File a pull request with your change and request review from [someone in the nf-osi organization](https://github.com/orgs/nf-osi/people).
5) If your pull request is accepted, we'll create a new release with your changes. 

## Guidelines for proposing new terms

Our strategy is to rely on annotation terms and definitions that have already been made and standardized whenever possible for use with Sage Bionetworks supported communities. In general, we will not include terms in this repository that are not needed and vetted by our communities - but don't let that stop you from using this! Feel free to fork and include terminology that you require for your own use.

If you are proposing a new term, then we require a source for the definition. The first place to look for an existing term is the EMBL-EBI Ontology Lookup Service. We have some preferred ontology term sources: EDAM, EFO, OBI, and NCIT. It's OK if your term comes from another source, but use the preferred sources whenever possible. You should use the term as defined in the source, or one of its synonyms. If your term does not currently exist, or has a different definition than existing ones, then:

    Provide a different source URL - this may be a Wikipedia entry, link to a commercial web site, or other URL.
    If you are a Sage Bionetworks employee and cannot find a source URL, then use "Sage Bionetworks" as the source and your own definition.
    If you are not (nor are you working with a Sage Bionetworks supported community) it is up to you for a strategy for controlling new terms to be added.

## Guidelines for specific term types
In some situations (e.g. drug names), terms are not always well-captured by the ontologies found in the Ontology Lookup Service. We've defined some best practices for contributing these terms here.

### Contribution of tumorType terms
ONCOTREE _names_ are the preferred tumorType values. 

### Contribution of drug terms
The preferred first-pass strategy for chemical name annotation is to search the EMBL-EBI ontology lookup service to find names, descriptions, and sources. Typically, the NCI Thesaurus will provide a suitable description for drugs and other biologically active molecules. In situations where the query molecule is not found in EMBL-EBI Ontology Lookup Service, a helpful secondary location to find chemical descriptions is MeSH.
In situations where novel molecules (such as newly-synthesized research compounds or proprietary pharmaceutical molecules) require annotation, the only suitable description and source might be the paper describing the synthesis or discovery, or information from the pharmaceutical company that created the identifier.

### Contribution of species terms
The preferred strategy for species name annotation is to search the NCBI Taxonomy Browser to find names, descriptions, and sources. The format of the description should be "Species name with taxonomy ID: taxonomyID and Genbank common name common name". The species name, taxonomyID, and Genbank common name can all be found in the NCBI Taxonomy Browser entry for the species.

### Contribution of file formats
We use the fileFormat key to indicate, well, the file format of a file uploaded to Synapse. Given the bias towards genomics files in Synapse, our source for file formats tends to come from EDAM, NCIT, but also Wikipedia and corporate web site descriptions. One thing to note is that the value to be contributed does not need to be the same as the commonly used file extension. For example, we describe GZipped files as gzip, while a GZipped file generally has an extension of gz.
