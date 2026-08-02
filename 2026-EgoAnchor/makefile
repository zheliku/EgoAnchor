SOURCE := egoanchor_cn_ai_v9.tex
OUTDIR := pdf
LATEXMK := latexmk
LATEXFLAGS := -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=$(OUTDIR)

.PHONY: all latest clean distclean

all latest: | $(OUTDIR)
	$(LATEXMK) $(LATEXFLAGS) $(SOURCE)

$(OUTDIR):
	mkdir $(OUTDIR)

clean:
	$(LATEXMK) -c -outdir=$(OUTDIR) $(SOURCE)

distclean:
	$(LATEXMK) -C -outdir=$(OUTDIR) $(SOURCE)
