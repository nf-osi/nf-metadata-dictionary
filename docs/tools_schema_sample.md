# Tools Schema Sample Report

Columns and representative values sampled from the Tools materialized view and
per-resource-type source tables, for use in designing OpenSearch facet structure.

## Tools Materialized View (syn51730943) (`syn51730943`)

Rows sampled: 500

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `resourceId` | 100.0% | 500 | '02dacc42-ea46-48fb-a4df-7a875d801086' (1), '09c988ab-765a-44ca-b2d7-1957b729208e' (1), '0a1a3741-0337-4067-95ab-fb0dc9562d66' (1), '0f404e70-2acf-4877-bcd5-6da81d9fa41e' (1), '1097f821-56c3-4e51-bcd3-f84aef506e3a' (1) |
| `rrid` | 93.2% | 466 | 'rrid:CVCL_YL59' (1), 'rrid:CVCL_3695' (1), 'rrid:CVCL_1B47' (1), 'rrid:CVCL_UI66' (1), 'rrid:CVCL_A258' (1) |
| `resourceName` | 100.0% | 500 | 'HEK293 NF1 -/- with R1306X mNf1 cDNA' (1), 'SZ-NF4' (1), 'HBE135-E6E7' (1), '90-8' (1), 'WT ES' (1) |
| `synonyms` | 100.0% | 639 | 'CSD23222' (2), 'CML_6M' (2), 'CML6M' (2), 'SZ-NF4 PGD' (1), 'NF#4' (1) |
| `description` | 59.0% | 150 | 'Lymphoblastoid cell line derived from B-lymphocytes' (32), 'Lymphoblastoid cell line derived from B-lymphocytes from an ' (23), 'MPNST tumor cell line from an NF1 patient.' (14), 'Mutation of NRAS, p.Gln61Arg (c.182A>G), Unspecified zygosit' (10), 'Mutation of NRAS, p.Gln61Lys (c.181C>A), Unspecified zygosit' (7) |
| `resourceType` | 100.0% | 1 | 'Cell Line' (500) |
| `investigatorName` | 18.4% | 19 | 'Margaret Wallace' (32), 'Deeann Wallis' (20), 'Robert A. Kesterson' (6), 'Tadashi Kondo' (6), 'Eduard Serra' (6) |
| `institution` | 18.0% | 17 | 'University of Florida' (32), 'The University of Alabama at Birmingham' (20), 'University of Alabama at Birmingham' (6), 'National Cancer Center Research Institute Japan' (6), "Fundació Institut d'Investigació en Ciències de la Salut Ger" (6) |
| `orcid` | 16.0% | 11 | '0000-0002-5202-8895' (32), '0000-0002-8217-0892' (20), '0000-0003-1331-0780' (6), '0000-0001-6405-7792' (6), '0000-0003-2895-9857' (6) |
| `usageRequirements` | 100.0% | 9 | 'Unknown' (410), 'special licencing restrictions (see vendor for more informat' (85), 'non-commercial use only' (3), 'generation of germ line transmitting chimeras not permitted' (3), 'creation of functional gametes not permitted' (3) |
| `howToAcquire` | 100.0% | 14 | 'We don’t know of a reliable source for this tool. If you do,' (311), 'This tool is available from a commercial vendor or non-profi' (130), 'To obtain this tool, please contact the originating investig' (20), 'To obtain this tool, please contact the originating investig' (12), 'To obtain this tool, please contact the originating investig' (6) |
| `species` | 100.0% | 6 | 'Homo sapiens' (476), 'Mus musculus' (21), 'Canis lupus familiaris' (4), 'Xenopus laevis' (2), 'Escherichia coli' (1) |
| `cellLineCategory` | 100.0% | 10 | 'Cancer cell line' (323), 'Transformed cell line' (59), 'Induced pluripotent stem cell' (33), 'Embryonic stem cell' (26), 'Telomerase immortalized cell line' (26) |
| `cellLineGeneticDisorder` | 100.0% | 2 | 'No known genetic disorder' (357), 'Neurofibromatosis type 1' (143) |
| `cellLineManifestation` | 100.0% | 42 | 'Melanoma' (170), 'General NF1 Deficiency' (40), 'Cutaneous Melanoma' (34), 'Neuroblastoma' (30), 'Cutaneous Neurofibroma' (20) |
| `backgroundStrain` | 0.0% | 0 | — |
| `backgroundSubstrain` | 0.0% | 0 | — |
| `animalModelGeneticDisorder` | 100.0% | 0 | — |
| `animalModelOfManifestation` | 100.0% | 0 | — |
| `insertName` | 0.0% | 0 | — |
| `insertSpecies` | 100.0% | 0 | — |
| `vectorType` | 100.0% | 0 | — |
| `targetAntigen` | 0.0% | 0 | — |
| `reactiveSpecies` | 100.0% | 0 | — |
| `hostOrganism` | 0.0% | 0 | — |
| `biobankName` | 0.0% | 0 | — |
| `biobankURL` | 0.0% | 0 | — |
| `specimenTissueType` | 100.0% | 0 | — |
| `specimenPreparationMethod` | 100.0% | 0 | — |
| `diseaseType` | 100.0% | 0 | — |
| `tumorType` | 100.0% | 0 | — |
| `specimenFormat` | 100.0% | 0 | — |
| `specimenType` | 100.0% | 0 | — |
| `contact` | 0.0% | 0 | — |
| `funderName` | 4.8% | 2 | 'Neurofibromatosis Therapeutic Acceleration Program' (20), 'Gilbert Family Foundation' (4) |
| `race` | 22.0% | 3 | 'White' (88), 'Asian' (16), 'Black' (6) |
| `sex` | 100.0% | 3 | 'Unknown' (198), 'Female' (161), 'Male' (141) |
| `age` | 43.6% | 83 | '62' (10), '61' (8), '8' (7), '54' (5), '19' (5) |
| `dateAdded` | 100.0% | 3 | '1687711051000' (399), '1634241592000' (88), '1649107963000' (13) |
| `dateModified` | 100.0% | 3 | '1698338340000' (399), '1634241592000' (87), '1649107963000' (14) |
| `latestPublicationDate` | 68.0% | 68 | '2014-03-01' (161), '2016-01-13' (34), '2019-02-25' (11), '2020-09-28' (10), '2012-01-04' (9) |
| `completenessCategory` | 100.0% | 3 | 'Fair' (346), 'Good' (150), 'Excellent' (4) |
| `availabilityCategory` | 100.0% | 2 | 'Some' (457), 'All' (43) |
| `criticalInfoCategory` | 100.0% | 1 | 'All' (500) |
| `otherInfoCategory` | 100.0% | 2 | 'No' (378), 'All' (122) |
| `observationCategory` | 100.0% | 3 | 'No' (395), 'Some' (102), 'All' (3) |

## Tools MV — Cell Line subset (`syn51730943`)

Rows sampled: 500

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `resourceId` | 100.0% | 500 | '02dacc42-ea46-48fb-a4df-7a875d801086' (1), '09c988ab-765a-44ca-b2d7-1957b729208e' (1), '0a1a3741-0337-4067-95ab-fb0dc9562d66' (1), '0f404e70-2acf-4877-bcd5-6da81d9fa41e' (1), '1097f821-56c3-4e51-bcd3-f84aef506e3a' (1) |
| `rrid` | 93.2% | 466 | 'rrid:CVCL_YL59' (1), 'rrid:CVCL_3695' (1), 'rrid:CVCL_1B47' (1), 'rrid:CVCL_UI66' (1), 'rrid:CVCL_A258' (1) |
| `resourceName` | 100.0% | 500 | 'HEK293 NF1 -/- with R1306X mNf1 cDNA' (1), 'SZ-NF4' (1), 'HBE135-E6E7' (1), '90-8' (1), 'WT ES' (1) |
| `synonyms` | 100.0% | 639 | 'CSD23222' (2), 'CML_6M' (2), 'CML6M' (2), 'SZ-NF4 PGD' (1), 'NF#4' (1) |
| `description` | 59.0% | 150 | 'Lymphoblastoid cell line derived from B-lymphocytes' (32), 'Lymphoblastoid cell line derived from B-lymphocytes from an ' (23), 'MPNST tumor cell line from an NF1 patient.' (14), 'Mutation of NRAS, p.Gln61Arg (c.182A>G), Unspecified zygosit' (10), 'Mutation of NRAS, p.Gln61Lys (c.181C>A), Unspecified zygosit' (7) |
| `resourceType` | 100.0% | 1 | 'Cell Line' (500) |
| `investigatorName` | 18.4% | 19 | 'Margaret Wallace' (32), 'Deeann Wallis' (20), 'Robert A. Kesterson' (6), 'Tadashi Kondo' (6), 'Eduard Serra' (6) |
| `institution` | 18.0% | 17 | 'University of Florida' (32), 'The University of Alabama at Birmingham' (20), 'University of Alabama at Birmingham' (6), 'National Cancer Center Research Institute Japan' (6), "Fundació Institut d'Investigació en Ciències de la Salut Ger" (6) |
| `orcid` | 16.0% | 11 | '0000-0002-5202-8895' (32), '0000-0002-8217-0892' (20), '0000-0003-1331-0780' (6), '0000-0001-6405-7792' (6), '0000-0003-2895-9857' (6) |
| `usageRequirements` | 100.0% | 9 | 'Unknown' (410), 'special licencing restrictions (see vendor for more informat' (85), 'non-commercial use only' (3), 'generation of germ line transmitting chimeras not permitted' (3), 'creation of functional gametes not permitted' (3) |
| `howToAcquire` | 100.0% | 14 | 'We don’t know of a reliable source for this tool. If you do,' (311), 'This tool is available from a commercial vendor or non-profi' (130), 'To obtain this tool, please contact the originating investig' (20), 'To obtain this tool, please contact the originating investig' (12), 'To obtain this tool, please contact the originating investig' (6) |
| `species` | 100.0% | 6 | 'Homo sapiens' (476), 'Mus musculus' (21), 'Canis lupus familiaris' (4), 'Xenopus laevis' (2), 'Escherichia coli' (1) |
| `cellLineCategory` | 100.0% | 10 | 'Cancer cell line' (323), 'Transformed cell line' (59), 'Induced pluripotent stem cell' (33), 'Embryonic stem cell' (26), 'Telomerase immortalized cell line' (26) |
| `cellLineGeneticDisorder` | 100.0% | 2 | 'No known genetic disorder' (357), 'Neurofibromatosis type 1' (143) |
| `cellLineManifestation` | 100.0% | 42 | 'Melanoma' (170), 'General NF1 Deficiency' (40), 'Cutaneous Melanoma' (34), 'Neuroblastoma' (30), 'Cutaneous Neurofibroma' (20) |
| `backgroundStrain` | 0.0% | 0 | — |
| `backgroundSubstrain` | 0.0% | 0 | — |
| `animalModelGeneticDisorder` | 100.0% | 0 | — |
| `animalModelOfManifestation` | 100.0% | 0 | — |
| `insertName` | 0.0% | 0 | — |
| `insertSpecies` | 100.0% | 0 | — |
| `vectorType` | 100.0% | 0 | — |
| `targetAntigen` | 0.0% | 0 | — |
| `reactiveSpecies` | 100.0% | 0 | — |
| `hostOrganism` | 0.0% | 0 | — |
| `biobankName` | 0.0% | 0 | — |
| `biobankURL` | 0.0% | 0 | — |
| `specimenTissueType` | 100.0% | 0 | — |
| `specimenPreparationMethod` | 100.0% | 0 | — |
| `diseaseType` | 100.0% | 0 | — |
| `tumorType` | 100.0% | 0 | — |
| `specimenFormat` | 100.0% | 0 | — |
| `specimenType` | 100.0% | 0 | — |
| `contact` | 0.0% | 0 | — |
| `funderName` | 4.8% | 2 | 'Neurofibromatosis Therapeutic Acceleration Program' (20), 'Gilbert Family Foundation' (4) |
| `race` | 22.0% | 3 | 'White' (88), 'Asian' (16), 'Black' (6) |
| `sex` | 100.0% | 3 | 'Unknown' (198), 'Female' (161), 'Male' (141) |
| `age` | 43.6% | 83 | '62' (10), '61' (8), '8' (7), '54' (5), '19' (5) |
| `dateAdded` | 100.0% | 3 | '1687711051000' (399), '1634241592000' (88), '1649107963000' (13) |
| `dateModified` | 100.0% | 3 | '1698338340000' (399), '1634241592000' (87), '1649107963000' (14) |
| `latestPublicationDate` | 68.0% | 68 | '2014-03-01' (161), '2016-01-13' (34), '2019-02-25' (11), '2020-09-28' (10), '2012-01-04' (9) |
| `completenessCategory` | 100.0% | 3 | 'Fair' (346), 'Good' (150), 'Excellent' (4) |
| `availabilityCategory` | 100.0% | 2 | 'Some' (457), 'All' (43) |
| `criticalInfoCategory` | 100.0% | 1 | 'All' (500) |
| `otherInfoCategory` | 100.0% | 2 | 'No' (378), 'All' (122) |
| `observationCategory` | 100.0% | 3 | 'No' (395), 'Some' (102), 'All' (3) |

## Animal Model Source Table (`syn26486808`)

Rows sampled: 123

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `transplantationDonorId` | 0.8% | 1 | 'c8b2e7df-ff15-495a-9c2d-8de3123a5c2d' (1) |
| `animalModelId` | 100.0% | 123 | 'ec7b0006-e5e7-45ef-b0cf-ec6897d2f737' (1), '7d317330-8c91-43d6-90d9-e340c87d0455' (1), 'b75c336e-791d-4a62-b556-153c88b28960' (1), '77461def-0085-4fce-84d8-7c0c8da4c4d6' (1), 'cc53d626-bbc5-478e-8953-5bcd4cfe2340' (1) |
| `donorId` | 100.0% | 123 | '37e3618d-7246-4036-b1fa-e2f032b8077c' (1), 'a3a33c65-d120-4500-b3a4-e680c3a59de9' (1), 'be180150-374d-4459-9a81-398c8a34bca9' (1), 'd70ba323-d39a-48ef-b809-f8ec814a1161' (1), '6cbaf2e1-b6e1-4a9c-899b-fbe65c3f338d' (1) |
| `backgroundSubstrain` | 30.1% | 8 | 'C57BL/6J' (28), 'C57BL/6JGpt' (2), '129T2/SvEmsJ;C57Bl/6NTac Nf1+/- f' (2), 'C57BL/6J;129/SvJ' (1), '129S2/SvPas;C57BL/6' (1) |
| `strainNomenclature` | 14.6% | 18 | 'B6.129(Cg)-Nf1tm1Par/J' (1), 'B6.129S2-Nf1tm1Tyj/J' (1), 'B6.129S6-Nf1tm1Fcr/J' (1), 'B6;129S2-Trp53tm1Tyj Nf1tm1Tyj/J' (1), 'B6.129S1-Nf1tm1Cbr/J' (1) |
| `backgroundStrain` | 59.3% | 13 | 'C57BL/6' (58), '129Sv;C57BL/6' (3), '129T2/SvEms;C57BL/6' (2), 'Ossabaw' (1), '129Sv' (1) |
| `animalModelOfManifestation` | 100.0% | 18 | 'Plexiform Neurofibroma' (7), 'Malignant Peripheral Nerve Sheath Tumor' (5), 'Cognition' (4), 'Metabolic Function' (2), 'Mild Or No Symptoms' (2) |
| `animalModelGeneticDisorder` | 100.0% | 1 | 'Neurofibromatosis type 1' (123) |
| `transplantationType` | 0.0% | 0 | — |
| `animalState` | 100.0% | 4 | 'live' (99), 'Not Available' (13), 'mouse cells' (6), 'embryo' (5) |
| `generation` | 9.8% | 5 | 'F1' (5), '>30' (3), '6' (2), 'F6' (1), '11' (1) |

## Antibody Source Table (`syn26486811`)

Rows sampled: 261

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `cloneId` | 27.2% | 35 | 'McNFn27a' (16), 'McNFn27b' (10), '2D1' (2), 'McNFn27' (2), 'D7R7D' (2) |
| `uniprotId` | 0.0% | 0 | — |
| `antibodyId` | 100.0% | 261 | '3b2701a5-ee6c-4c03-a39d-68303d61a328' (1), '47ca73c9-cc64-4247-b293-19a09ec4c6a3' (1), '16e06703-8ab6-413c-b7cc-2df8e57405d4' (1), '3f9fc0ea-1634-48af-a23f-0260d976bbec' (1), 'b8d23287-c76d-401c-b712-6d37dfdf9de5' (1) |
| `reactiveSpecies` | 100.0% | 19 | 'Human' (222), 'Mouse' (161), 'Rat' (140), 'Guinea pig' (24), 'Cow' (10) |
| `hostOrganism` | 100.0% | 3 | 'Rabbit' (187), 'Mouse' (73), 'Unknown' (1) |
| `conjugate` | 100.0% | 2 | 'Nonconjugated' (168), 'Conjugated' (93) |
| `clonality` | 100.0% | 3 | 'Polyclonal' (178), 'Monoclonal' (78), 'Unknown' (5) |
| `targetAntigen` | 100.0% | 30 | 'NF1' (219), 'NF1 (N-term)' (4), 'NF1 (aa 160-270)' (3), 'NF1 (C-term)' (3), 'NF1 (aa 2760 C-term)' (2) |

## Cell Line Source Table (`syn26486823`)

Rows sampled: 500

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `cellLineId` | 100.0% | 500 | 'a93bd0ae-d324-4a28-b08d-318c2a1f2216' (1), '37330961-9056-4f32-b6a6-81730e72d9f8' (1), 'fcf0af10-c8e1-4d50-bbd4-ea06cd019019' (1), '8d8b30b1-ef42-471c-8e92-262b32231544' (1), '6db1b979-1bef-4c6e-a3c0-10498b9c91ca' (1) |
| `donorId` | 100.0% | 489 | 'fc3bdaf4-1d01-42fa-8013-d18d3fbf48ae' (3), '40131d15-7037-474f-8c2d-0adeb6097432' (2), '51079b9b-1bc9-4437-a8a3-7ceb891a416c' (2), '3a2658cd-7b35-4ace-9101-84c6bfd87fdc' (2), '76659864-f267-418b-b14c-27285c550bf3' (2) |
| `originYear` | 0.0% | 0 | — |
| `organ` | 19.6% | 8 | 'Lung' (27), 'Pancreas' (22), 'Intestine' (19), 'Lymph Node' (11), 'Brain' (8) |
| `strProfile` | 0.0% | 0 | — |
| `tissue` | 12.2% | 5 | 'Primary tumor' (22), 'Bone marrow' (15), 'Embryonic tissue' (12), 'Nerve tissue' (11), 'Blood' (1) |
| `cellLineManifestation` | 100.0% | 54 | 'Melanoma' (176), 'Cutaneous Melanoma' (62), 'Neuroblastoma' (30), 'General NF1 Deficiency' (29), 'Malignant Peripheral Nerve Sheath Tumor' (19) |
| `resistance` | 0.0% | 0 | — |
| `cellLineCategory` | 100.0% | 6 | 'Cancer cell line' (444), 'Embryonic stem cell' (26), 'Finite cell line' (17), 'Hybrid cell line' (5), 'Induced pluripotent stem cell' (5) |
| `contaminatedMisidentified` | 0.0% | 0 | — |
| `cellLineGeneticDisorder` | 100.0% | 2 | 'No known genetic disorder' (406), 'Neurofibromatosis type 1' (94) |
| `populationDoublingTime` | 17.0% | 76 | '26 hours' (4), '27 hours' (2), '37 hours' (2), '38 hours' (2), '24 hours' (2) |

## Genetic Reagent Source Table (`syn26486832`)

Rows sampled: 122

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `vectorType` | 100.0% | 10 | 'Gateway Entry Clone' (64), 'Transfer Vector' (39), 'Yeast Expression' (5), 'Lentiviral' (4), 'RNAi' (3) |
| `insertEntrezId` | 97.5% | 8 | '16653' (49), '4763' (40), '3265' (12), '4893' (8), '24592' (4) |
| `geneticReagentId` | 100.0% | 122 | 'e0c8bf58-0668-4df7-92e5-89e395f647ef' (1), '41f912f0-660c-4d91-85f3-bded9ca24ced' (1), '3c539ba4-eb09-4f72-9a18-f6c36a7b6f5b' (1), '94e922a4-83f2-4c82-bd40-9af27008e744' (1), 'c4c1a6f4-f765-4f94-852b-bb6365459937' (1) |
| `5primer` | 64.8% | 4 | "M13F 23-mer (5'-CCCAGTCACGACGTTGTAAAACG)" (63), 'T7 (TAATACGACTCACTATAG)' (12), "T7(5' TAATACGACTCACTATAGGG 3' )" (3), 'pMB1ori-seqF: agggggaaacgcctggtatc; hsNF1-seqR1: taactgctaac' (1) |
| `cloningMethod` | 88.5% | 2 | 'Gateway Cloning' (64), 'Restriction Enzyme' (44) |
| `copyNumber` | 59.0% | 3 | 'High Copy' (65), 'Low Copy' (6), 'Unknown' (1) |
| `insertSpecies` | 100.0% | 3 | 'Homo sapiens' (109), 'Mus musculus' (10), 'Rattus norvegicus' (5) |
| `nTerminalTag` | 0.0% | 0 | — |
| `cTerminalTag` | 0.0% | 0 | — |
| `totalSize` | 65.6% | 19 | '3530' (40), '3533' (12), '3536' (7), '10788' (3), '10725' (3) |
| `5primeCloningSite` | 19.7% | 7 | 'SgfI' (12), 'HindIII' (6), 'NcoI' (2), 'kpnl' (1), 'Mlul' (1) |
| `growthTemp` | 71.3% | 1 | '37 C' (87) |
| `insertName` | 100.0% | 12 | 'KRAS' (50), 'NF1' (36), 'HRAS' (15), 'NRAS' (8), 'NF1 type 2 mini-gene' (3) |
| `bacterialResistance` | 82.8% | 5 | 'Spectinomycin' (63), 'Ampicillin' (27), 'Kanamycin' (8), 'Chloramphenicol' (2), 'Ampicillin and Bleocin (Zeocin)' (1) |
| `hazardous` | 100.0% | 1 | 'Unknown' (122) |
| `3primer` | 64.8% | 4 | "attLR 23-mer (5'-TAACATCAGAGATTTTGAGACAC)" (63), 'T7 terminator (GCTAGTTATTGCTCAGCGG)' (12), "BGH(5' TAGAAGGCACAGTCGAGG 3' )" (3), 'hsNF1-seqF13: cagtgttgtgtttcccaaagtc; pGEX-seqR: cctgacgggct' (1) |
| `5primeSiteDestroyed` | 71.3% | 2 | 'Unknown' (85), 'No' (2) |
| `3primeSiteDestroyed` | 71.3% | 3 | 'Unknown' (85), 'Yes' (1), 'No' (1) |
| `promoter` | 32.8% | 5 | 'CMV' (19), 'T7' (15), 'ADH' (4), 'U6' (1), 'ADH1' (1) |
| `backboneSize` | 73.8% | 9 | '2693' (63), '5723' (12), '2203' (6), '7510' (4), '9359' (1) |
| `insertSize` | 88.5% | 35 | '567' (43), '570' (13), '573' (7), '63' (4), '8663' (3) |
| `vectorBackbone` | 97.5% | 25 | 'pDonor-255' (63), 'pET15_NESG' (12), 'pCMV6-Entry' (7), 'pAMP-CY1' (6), 'pADANS' (5) |
| `growthStrain` | 71.3% | 3 | 'DH10B' (63), 'DH5alpha' (16), 'NEB Stable' (8) |
| `3primeCloningSite` | 19.7% | 7 | 'MluI' (12), 'SacII' (5), 'NotI' (2), 'HindIII' (2), 'Pvull' (1) |
| `gRNAshRNASequence` | 1.6% | 2 | 'GCTGGCAGTTTCAAACGTAA' (1), 'GATTATCCGAATTCTTAGCA' (1) |
| `selectableMarker` | 18.0% | 6 | 'Neomycin' (10), 'Kanamycin' (4), 'Puromycin' (3), 'Hygromycin' (3), 'Chloramphenicol' (1) |

## Biobank Source Table (`syn26486821`)

Rows sampled: 4

| Column | Coverage % | Unique vals | Top values |
|--------|-----------|-------------|------------|
| `biobankId` | 100.0% | 4 | 'd6f86049-4dc0-4543-bf99-0311eb44cb6e' (1), '674650f1-dcd7-4342-8c1a-d17b141b4954' (1), 'ab5b4481-c6ca-4c4f-9d03-207abba8462f' (1), 'f5ee8a4e-ce1d-450f-bf49-6a2af20176aa' (1) |
| `resourceId` | 100.0% | 4 | '17ad02e9-22c2-429e-8f1f-361adba1e0d7' (1), 'e4e60a43-9073-4dfa-a629-76b472451b7f' (1), '60e2d28b-9bf1-40e4-a0a1-dc3ef71b0e6d' (1), '2cd992ee-4232-4fad-9eca-26fd91dd20df' (1) |
| `diseaseType` | 100.0% | 1 | 'Neurofibromatosis type 1' (4) |
| `biobankURL` | 100.0% | 4 | 'https://www.hopkinsmedicine.org/kimmel-cancer-center/cancers' (1), 'https://www.ctf.org/research-tools-resources/#biobank' (1), 'https://www.coriell.org/1/Browse/Biobanks' (1), 'https://www.synapse.org/Synapse:syn68208858' (1) |
| `biobankName` | 100.0% | 4 | 'The Johns Hopkins NF1 Biospecimen Repository' (1), 'CTF Biobank' (1), 'Coriell Institute for Medical Research Biobank' (1), "Children's Hospital of Philadelphia" (1) |
| `specimenPreparationMethod` | 100.0% | 6 | 'Flash frozen' (2), 'FFPE' (2), 'Cryopreserved' (2), 'Formalin-fixed' (2), 'RNA later' (1) |
| `specimenType` | 100.0% | 4 | 'human tissue' (4), 'cell lines' (2), 'xenograft tumors' (1), 'blood' (1) |
| `tumorType` | 100.0% | 8 | 'malignant peripheral nerve sheath tumor' (2), 'plexiform neurofibroma' (2), 'neurofibroma NOS' (2), 'cutaneous neurofibroma' (1), 'atypical neurofibroma' (1) |
| `specimenFormat` | 100.0% | 5 | 'DNA' (4), 'RNA' (4), 'whole tumor' (3), 'whole cell lysate' (1), 'cells' (1) |
| `specimenTissueType` | 100.0% | 6 | 'Tumor' (4), 'Blood' (4), 'Brain' (2), 'Bone' (1), 'Cerebrospinal Fluid' (1) |
| `contact` | 25.0% | 1 | 'Please navigate to specimen inventory sheet to learn more ab' (1) |
