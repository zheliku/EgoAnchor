SOURCE := egoanchor_cn_v6.tex
OUTDIR := pdf
JOBNAME := EgoAnchor
FINAL := $(OUTDIR)/$(JOBNAME).pdf
LATEXMK := latexmk
LATEXFLAGS := -xelatex -interaction=nonstopmode -halt-on-error -jobname=$(JOBNAME) -outdir=$(OUTDIR)

.PHONY: all latest clean

all: $(FINAL)

latest: $(FINAL)

$(OUTDIR):
	mkdir $(OUTDIR)

$(FINAL): $(SOURCE) vgtc.cls | $(OUTDIR)
	$(LATEXMK) $(LATEXFLAGS) $(SOURCE)

clean:
	$(LATEXMK) -C -jobname=$(JOBNAME) -outdir=$(OUTDIR) $(SOURCE)
