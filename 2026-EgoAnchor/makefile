VERSIONS := 6
OUTDIR := pdf
TEXFILES := $(addprefix egoanchor_cn_v,$(addsuffix .tex,$(VERSIONS)))
PDFFILES := $(addprefix $(OUTDIR)/egoanchor_cn_v,$(addsuffix .pdf,$(VERSIONS)))
LATEXMK := latexmk
LATEXFLAGS := -xelatex -interaction=nonstopmode -halt-on-error -outdir=$(OUTDIR)

.PHONY: all latest clean

all: $(PDFFILES)

latest: $(OUTDIR)/egoanchor_cn_v6.pdf

$(OUTDIR):
	mkdir $(OUTDIR)

$(OUTDIR)/egoanchor_cn_v%.pdf: egoanchor_cn_v%.tex vgtc.cls | $(OUTDIR)
	$(LATEXMK) $(LATEXFLAGS) $<

clean:
	$(LATEXMK) -C -outdir=$(OUTDIR) $(TEXFILES)
