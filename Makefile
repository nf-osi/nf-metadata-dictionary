all: convert

# TODO Implement analysis on data model changes
analyze:
	@echo "Analyzing data model..."

convert:
	bb ./retold/retold as-jsonld --dir modules --out NF.jsonld 

