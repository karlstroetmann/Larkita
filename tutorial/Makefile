# Builds the tutorial.  The examples are run first, since the tutorial includes their outputs.

larkita-tutorial.pdf: larkita-tutorial.tex examples/*.g examples/*.py ../larkita/*.py
	cd examples && python3 run_examples.py
	pdflatex -shell-escape -interaction=nonstopmode -halt-on-error larkita-tutorial.tex
	pdflatex -shell-escape -interaction=nonstopmode -halt-on-error larkita-tutorial.tex
	pdflatex -shell-escape -interaction=nonstopmode -halt-on-error larkita-tutorial.tex

clean:
	rm -rf _minted* *.aux *.log *.toc larkita-tutorial.out examples/*.out examples/__pycache__
