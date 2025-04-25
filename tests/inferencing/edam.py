#!/usr/bin/env python3

# Minimally tests/demonstrates working integration with EDAM via (limited OWL-RL) inferencing. 
# Pull [EDAM](https://edamontology.org/EDAM_stable.owl), fuse with NF.ttl,
# generate inferenced triples, and assert some expected new triples/knowledge present.

import sys
import rdflib
import owlrl

edamG = rdflib.Graph().parse("https://edamontology.org/EDAM_stable.owl")
nfG = rdflib.Graph().parse("../dist/NF.ttl")
interG = edamG + nfG
interG.update("INSERT DATA {linkml:meaning owl:sameAs owl:equivalentClass}")

# https://owl-rl.readthedocs.io/en/latest/stubs/owlrl.DeductiveClosure.html#owlrl.DeductiveClosure
owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(interG)

# q = query ; r = result ; a = expected answer
##############################################

# Which formats are image formats (in NF, filter out EDAM)
q1 = """
SELECT ?s
WHERE {
  ?s rdfs:subClassOf <http://edamontology.org/format_3547> 
  FILTER NOT EXISTS { ?s <http://www.geneontology.org/formats/oboInOwl#inSubset> <http://purl.obolibrary.org/obo/edam#edam> .}
}
"""
a1 = ["https://w3id.org/synapse/nfosi/vocab/png", "https://w3id.org/synapse/nfosi/vocab/svg", 
      "https://w3id.org/synapse/nfosi/vocab/bgzip", "https://w3id.org/synapse/nfosi/vocab/ome-tiff",
      "https://w3id.org/synapse/nfosi/vocab/jpg", "https://w3id.org/synapse/nfosi/vocab/MPEG-4",
      "https://w3id.org/synapse/nfosi/vocab/bmp"]
result = interG.query(q1)
for row in result:
    print(f"{row.s}")

assert all(str(format) in [str(r.s) for r in result] for format in a1), "Not all expected image formats found in results"

# What are all subtypes of gene expression data?
q2 = """
SELECT ?l
WHERE {
  ?s rdfs:subClassOf+ <https://w3id.org/synapse/nfosi/vocab/gene%20expression> .
  ?s rdfs:label ?l
}
"""
result = interG.query(q2)
for row in result:
    print(f"{row.l}")

# (Requires EDAM-next/unstable version) What operation has as output the data sharing plan
q3 = """
PREFIX edam: <http://edamontology.org/>

SELECT ?name WHERE {
  ?o rdfs:subClassOf ?restriction .
  ?restriction rdf:type owl:Restriction .
  ?restriction owl:onProperty edam:has_output.
  ?restriction owl:someValuesFrom <https://w3id.org/synapse/nfosi/vocab/data%20sharing%20plan> .
  ?o rdfs:label ?name
}
"""
result = interG.query(q3)
