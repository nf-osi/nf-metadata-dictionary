library(visNetwork)
library(tidyverse)

#-------------------------------------------------------------------------------#

# Reads a main extended schematic .csv file and its extended definitions
# (which are separate files named `ext_classes.csv` and `ext_relations.csv`,
# respectively)
# usage example:
# schema <- readExtSchema("NF.csv")
readExtSchema <- function(schema_csv, ext_classes_csv = "ext_classes.csv") {
  schema <- read.csv(schema_csv) %>%
    select(label = Attribute, id = .ID, Root = .Root, SubclassOf = .SubclassOf)
  
  # Extended class definitions
  ext_classes <- read.csv(ext_classes_csv) %>%
    select(label = Attribute, id = .ID, Root = .Root, SubclassOf = .SubclassOf)
  
  ext_schema <- rbind(schema, ext_classes)
  ext_schema
}

#' Make required node and edge data for specified cluster
#' Usage:
#' assay <- getNodesEdges(schema, "Assay", "A", 
#' nodes = list(color = list(A = "plum", C = "indigo")))
#' template <- getNodesEdges(schema, "Template", "T", use_id = T, 
#' nodes = list(color = list(A = "pink", C = "firebrick")))
getNodesEdges <- function(schema, cluster_root, 
                          prefix, use_id = F,
                          nodes = list(color = list(A = "black", C = "black"),
                                       font.color = list(A = "white", C = "white"))
                          ) {
  cluster <- schema %>% 
    filter(Root == cluster_root)
  
  # Namespaces for cluster ancestor vs Children
  A <- paste(prefix, "A", sep = "_")
  C <- paste(prefix, "C", sep = "_")
  nodes <- cluster %>%
    select(id, label, SubclassOf) %>%
    mutate(group = ifelse(SubclassOf %in% c(cluster_root, ""), A, C),
           color = ifelse(group == A, nodes$color$A, nodes$color$C),
           font.color = ifelse(group == A, nodes$font.color$A, nodes$font.color$C)) 
  
  if(use_id) {
    nodes <- nodes %>%
      mutate(label = id)
  }
  
  edges <- cluster %>%
    filter(SubclassOf != "") %>% # Remove root from edges
    select(from = id, to = SubclassOf)
  
  return(list(nodes = nodes, edges = edges))
}

# Convenience wrapper to extract and combine two clusters into a graph df 
# given schema and extensions
# usage example:
# c2Cluster(assay, template)
c2Cluster <- function(cluster_1, cluster_2, connect_by, 
                      ext_relations_csv = "ext_relations.csv",
                      viz = list(color = "firebrick", width = 4)) {
  
  # Configure between-cluster relations
  relations <- read.csv(ext_relations_csv, header = T)
  edges <- relations %>%
    filter(property == connect_by)
  relations$color <- viz$color
  relations$width <- viz$width
  
  # Concatenate clusters
  g_nodes <- rbind(cluster_1$nodes, cluster_2$nodes)
  g_edges <- rbind(cluster_1$edges, cluster_2$edges)
  g_edges$color <- "gray" # non-configurable default for now
  g_edges$width <- 1 # non-configurable default for now
  g_edges <- rbind(g_edges, relations[, c("from", "to", "color", "width")])
  return(list(nodes = g_nodes, edges = g_edges))
}

# Generate default graph
defaultGraph <- function(graph, height = 800) {
  visNetwork(graph$nodes, graph$edges, height = height) %>%
    visEdges(arrows = "To") %>%
    visIgraphLayout() %>%
    visNodes(shape = "box",
             font = list(size = 30),
             shadow = list(enabled = TRUE),
             physics = F) %>%
    visOptions(nodesIdSelection = TRUE, 
               highlightNearest = list(enabled = T, hover = T)
               )
}

# Simple graph function meant for checking an extracted portion of graph
basicGraph <- function(g) {
  visNetwork(g$nodes, g$edges) %>%
  visEdges(arrows = "To") %>%
  visIgraphLayout()
}

# ------------------------------------------------------------------------------#
