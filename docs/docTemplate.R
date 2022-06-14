#' Generate template documentation
#' 
#' Basically tries to present a template in a conventional format similar to:
#' 1. [Bioschema profile](https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE)
#' 2. [FAIRplus example](https://fairplus.github.io/the-fair-cookbook/content/recipes/interoperability/transcriptomics-metadata.html#assay-metadata)
#' 3. [Immport template doc](https://www.immport.org/shared/templateDocumentation?tab=1&template=bioSamples.txt)
#' 4. [LINCS template doc](https://lincsproject.org/LINCS/files//2020_exp_meta_stand/General_Proteomics.pdf)
#' 
#' In general it looks like a table with one row per property and informational columns for:
#' - [x] controlled values (valid values for schematic) / range of property
#' - [ ] marginality (required vs. recommended vs. optional)
#' - [ ] cardinality (one or many values allowed)
#' - [x] notes / comments
#' 
#' Currently, schematic templates allow modeling more on the simplistic side and 
#' don't formally express all these, so only a few are checked.
#' Moreover, the jsonld version encodes much less information than the csv version
#' (jsonld conversion loses custom metadata in the csv), which is why this currently depends on both formats. 
#' 
#' @param templates Named vector of templates to process,
#' where names corresponds to id without prefix (currently whatever follows "bts:"),
#' and value is the real internal ID (in .ID).
#' @param schema_csv Schema representation read from `.csv`.
#' @param schema_jsonld Schema path to jsonld file.
#' @param savedir Directory where template representations will be outputted.
docTemplate <- function(templates,
                        schema_csv,
                        schema_jsonld = "../NF.jsonld",
                        savedir = "templates/") {
  
  
  for(x in names(templates)) {  # e.g. x <- "GenomicsAssayTemplate"
    # For template, parse DependsOn to get all props present in manifest
    props <- nfportalutils::get_dependency_from_json_schema(paste0("bts:", x), 
                                                            schema = schema_jsonld)
    
    # Create the ControlledVocab aka Range col for each prop
    # ControlledVocab col is handled specially and uses a custom Range col defined in csv
    # For CV col we create a link to a class if the term editor has referenced a class in Range, 
    # else we simply fall back to enumerating the valid values
    index <- match(props, schema_csv$Attribute)
    range <- dplyr::if_else(schema_csv[index, "Range"] != "", 
                            paste0("#", schema_csv[index, "Range"]), 
                            schema_csv[index, "Valid.Values"])
    
    template_tab <- data.frame(Field = props,
                               Description = schema_csv[index, "Description"],
                               Required = ifelse(schema_csv[index, "Required"], "required", "optional"),
                               ControlledVocab = range,
                               # Cardinality = schema_csv[index, "Cardinality"],
                               Note = schema_csv[index, "EditorNote"])
    
    template_id <- templates[x]
    filepath <-  paste0(savedir, template_id, ".csv")
    write.csv(template_tab, file = filepath, row.names = F)
  }
}


