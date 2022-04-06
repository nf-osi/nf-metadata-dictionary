all: collate convert

collate:
	@echo "Collating module components..."
	head -1 modules/Assay/Assay.csv > ${CSV}
	tail -n +2 -q modules/*/*.csv >> ${CSV}

convert:
	schematic schema convert ${CSV}
