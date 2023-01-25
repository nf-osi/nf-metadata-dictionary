library(nfportalutils)
library(data.table)

PROD_DB <- "syn26438037"
RESOURCE_TYPE <- "Cell Line"
CELL_LINE_FILE <- "modules/Sample/Cell_Line_Model.csv"
MOUSE_MODEL_FILE <- "modules/Sample/Mouse_Model.csv"

# property
PROPERTY_FILE <- "modules/Sample/annotationProperty.csv"

syn_login()

result <- .syn$tableQuery(glue::glue("select resourceName,description,resourceId from {PROD_DB} where resourceType='{RESOURCE_TYPE}'"), includeRowIdAndRowVersion = FALSE)
df <- as.data.table(result$asDataFrame())
setnames(df, c("Attribute", "Description", ".ID"))
n_result <- nrow(df)

csv <- fread(CELL_LINE_FILE, colClasses = "character")
csv <- csv[!is.na(Attribute), ]
n_csv <- nrow(csv)

new_records <- df[!duplicated(Attribute)][!Attribute %in% csv$Attribute, ]
n_new <- nrow(new_records)

combined <- rbind(csv, new_records, fill = TRUE, use.names = TRUE)
setkey(combined, "Attribute") # merely for more readable diffs

# Fill in with default values
combined[, Required := FALSE]
combined[, Parent := "modelSystemName"]
combined[, .Root := "Model_System"]
combined[, .SubOf := "Cell_Line_Model"]
combined[, .Type := "Class"]  
combined[, .Module := "Biosample"] 
records_combined <- nrow(combined)

cat("Sync added", n_new, "new entities\n")

fwrite(combined, file = CELL_LINE_FILE)

## Update annotationProperty
cell_line_names <- combined$Attribute
mouse_model <- fread(MOUSE_MODEL_FILE, colClasses = "character")
mouse_model_names <- mouse_model$Attribute

values <- paste(c(cell_line_names, mouse_model_names), collapse = ",")
properties <- fread(PROPERTY_FILE)
properties$`Valid Values`[properties$Attribute == "modelSystemName"] <- values
fwrite(properties, file = PROPERTY_FILE)
