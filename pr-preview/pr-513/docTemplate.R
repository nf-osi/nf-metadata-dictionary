read_properties <- function(file = "../modules/props.yaml") {
  props <- yaml::read_yaml(file)$slots
  # props <- rbindlist(props, fill = TRUE, idcol = "Property")
  props
}

# The range of prop `assay` is anything of class `Assay` --
# However, the json-ld does not make this so conceptually concise for props, instead listing all possible values
# In the docs, we don't want to enumerate all values and instead want to create a _link_ to a class that defines the range
# To do this, we can infer class by look up the class of the first listed enum for that prop
# The range could also be inferred to be a boolean or string/integer rather than a class
summarize_range <- function(prop_id, schema, return_labels = FALSE) {
  
  enums <- nfportalutils::get_by_prop_from_json_schema(id = prop_id,
                                                       prop = "schema:rangeIncludes",
                                                       schema = schema,
                                                       return_labels = FALSE)
  
  # handle how enums are presented
  if(is.null(enums)) return("")
  if(length(enums) < 5) return(paste(gsub("bts:", "", enums), collapse = ","))
  if("bts:Yes" %in% enums) return("Y/N")
  
  enum1 <- enums[1]
  
  # additional lookup class
  class <- nfportalutils::get_by_prop_from_json_schema(enum1, 
                                                       prop = "rdfs:subClassOf", 
                                                       schema = schema,
                                                       return_labels = FALSE)[[1]] 
  if(length(class) > 1) warning(enum1, " has multiple parent classes")
  class <- sub("bts:", "", class[1]) # use first but warn
  class <- paste0("#", class)
  class
}

#' @param prop_id Namespaced id, e.g. "bts:tumorType"
summarize_range_linkml <- function(prop_id, props) {
  prop_id <- sub("^bts:", "", prop_id)
  
  # union ranges
  if(!is.null(props[[prop_id]]$any_of)) {
    paste0("#", unlist(props[[prop_id]]$any_of, use.names = F), collapse = "|")
    
  } else {
    class <- props[[prop_id]]$range
    if(is.null(range)) class <- ""
    paste0("#", class)
  }
}


#' Generate template documentation
#' 
#' Basically tries to present a template in a conventional format similar to:
#' 1. [GDC viewer](https://docs.gdc.cancer.gov/Data_Dictionary/viewer/#?view=table-definition-view&id=aligned_reads)
#' 2. [Bioschema profile](https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE)
#' 3. [FAIRplus example](https://fairplus.github.io/the-fair-cookbook/content/recipes/interoperability/transcriptomics-metadata.html#assay-metadata)
#' 4. [Immport template doc](https://www.immport.org/shared/templateDocumentation?tab=1&template=bioSamples.txt)
#' 5. [LINCS template doc](https://lincsproject.org/LINCS/files//2020_exp_meta_stand/General_Proteomics.pdf)
#' 
#' In general it looks like a table with one row per property and informational columns for:
#' - [x] controlled values (valid values for schematic) / range of property
#' - [ ] marginality (required vs. recommended vs. optional)
#' - [ ] cardinality (one or many values allowed)
#' - [x] notes / comments
#' 
#' Currently, schematic templates allow modeling more on the simplistic side and 
#' don't formally express all these, so only a few are checked.
#' Currently, the jsonld version loses some information when translated from the csv source
#' (mainly the summary Range definition corresponding to https://www.w3.org/TR/rdf-schema/#ch_range and EditorNote).
#' 
#' @param templates Named vector of templates to process,
#' where names corresponds to id without prefix (currently whatever follows "bts:"),
#' and value is the real internal ID (in .ID).
#' @param schema Schema list object parsed from a schematic jsonld.
#' @param prefix Namespace prefix.
#' @param savedir Directory where template representations will be outputted.
#' @param verbose Whether to be verbose about what's going on.
docTemplate <- function(templates,
                        schema,
                        prefix = "bts:",
                        savedir = "templates/",
                        verbose = TRUE) {
  
  
  for(x in names(templates)) {  # e.g. x <- "GenomicsAssayTemplate"
    # For template, parse DependsOn to get all props present in manifest
    prop_ids <- nfportalutils::get_dependency_from_json_schema(paste0(prefix, x), 
                                                               schema = schema, 
                                                               return_labels = FALSE)
    
   
    prop_ref <- read_properties()
    
    sms <- Filter(function(x) x$`@id` %in% prop_ids, schema)
    sms <- lapply(sms, function(x) {
      list(Field = x$`sms:displayName`,
           Description = if(!is.null(x$`rdfs:comment`)) x$`rdfs:comment` else " ",
           Required = if(!is.null(x$`sms:required`)) sub("sms:", "", x$`sms:required`) else "?", 
           ValidRange = summarize_range_linkml(prop_id = x$`@id`, props = prop_ref))
    })
    tt <- rbindlist(sms)
    
    # Sort to show by required, then alphabetically
    tt <- tt[order(-Required, Field), ]
    
    template_id <- templates[x]
    filepath <-  paste0(savedir, template_id, ".csv")
    write.csv(tt, file = filepath, row.names = F)
  }
}


