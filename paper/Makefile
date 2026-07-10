# Paper build. `make` -> main.pdf ; `make tables` regenerates tables/*.tex from data/*.json.
# Tables are committed build products: the paper builds without re-running the benchmark, but
# always rerun `make tables` after refreshing data/ (see README.md for the data pipeline).

LATEXMK = latexmk -pdf -interaction=nonstopmode -halt-on-error

.PHONY: all tables clean distclean

all: tables main.pdf

main.pdf: main.tex references.bib $(wildcard sections/*.tex) $(wildcard tables/*.tex)
	$(LATEXMK) main

tables:
	python3 scripts/gen_tables.py

clean:
	latexmk -c main 2>/dev/null || true

distclean:
	latexmk -C main 2>/dev/null || true
