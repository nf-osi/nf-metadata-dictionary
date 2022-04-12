#' Function to generate template documentation
#' 
#' Creates one row per property and selected informational columns for:
#' - marginality (required vs. recommended vs. optional; in our case, recommended/optional collapsed to optional)
#' - controlled values / constraints on fields 
#' - cardinality (one or many values allowed) *currently omitted, see additional notes
#' Example related resources for what this can look like:
#' 1. https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE
#' 2. https://fairplus.github.io/the-fair-cookbook/content/recipes/interoperability/transcriptomics-metadata.html#assay-metadata
#' 3. https://www.immport.org/shared/templateDocumentation?tab=1&template=bioSamples.txt
#' 4. https://lincsproject.org/LINCS/files//2020_exp_meta_stand/General_Proteomics.pdf
#' Marginality is mentioned in all examples.
#' CV is mentioned for #1,2,3.
#' Cardinality is mentioned in #1 only, so it's not prioritized.
docTemplate <- function(schema, savedir = "templates/") {
    templates <- schema %>%
      filter(Root == "Template" & SubOf != "") %>%
      select(ID, DependsOn)
    for(template in templates$ID) {
      fields <- schema %>%
        filter(template == ID) %>% 
        pull(DependsOn) %>%
        strsplit(split = ", ?") %>% 
        unlist()
      index <- match(fields, schema$Attribute)
      # ControlledVocab col is handled specially and is derived from the Range col
      # Range is either filled with a class or blank, where blank means free text or Boolean values
      # Bools are "controlled vocabulary" vs. true ontology terms
      range <- dplyr::if_else(schema[index, "Range"] != "", paste0("#", schema[index, "Range"]), schema[index, "Valid.Values"])
      template_tab <- data.frame(Field = fields,
                                 Description = schema[index, "Description"],
                                 Required = ifelse(schema[index, "Required"], "required", "optional"),
                                 ControlledVocab = range,
                                # Cardinality = schema[index, "Cardinality"],
                                Note = schema[index, "EditorNote"])
      write.csv(template_tab, file = paste0(savedir, template, ".csv"), row.names = F) 
  }
}


