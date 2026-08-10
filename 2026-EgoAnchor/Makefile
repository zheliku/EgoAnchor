# EgoAnchor 中文论文工程构建。
#
# 所有中间产物（aux/bbl/blg/brf/fls/log/out/synctex.gz/xdv）与最终 PDF 一律写入
# pdf/，源目录只保留 .tex/.bib/.bst/.cls。latexmk 自动决定 bibtex 与重跑次数，
# 因此不会再出现「改了正文后引用变成问号」这类需要手工补跑 bibtex 的情况。
#
#   make            编译当前主稿
#   make MAIN=xxx   编译 xxx.tex（不带扩展名）
#   make ref FILE=reference/gpt-web/foo.tex
#                   在源目录为工作目录的前提下编译参考稿，
#                   产物落在该参考稿自己的 pdf/ 子目录，源目录不留副本
#   make clean      删除中间产物，保留 PDF
#   make distclean  删除 pdf/ 下全部产物

MAIN ?= egoanchor_cn_final_v3
OUTDIR := pdf
LATEXMK := latexmk
LATEXMKFLAGS := -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error

.PHONY: all ref clean distclean

all:
	$(LATEXMK) $(LATEXMKFLAGS) -outdir=$(OUTDIR) $(MAIN).tex

# 参考稿在原位编译：工作目录仍是源目录，因此 \input{tables/...} 与
# \includegraphics{figures/...} 的相对路径照常解析，无需把 .tex 复制到源目录。
ref:
	@test -n "$(FILE)" || (echo "用法: make ref FILE=reference/gpt-web/foo.tex" && exit 1)
	$(LATEXMK) $(LATEXMKFLAGS) -outdir=$(dir $(FILE))pdf "$(FILE)"

clean:
	$(LATEXMK) -c -outdir=$(OUTDIR) $(MAIN).tex

distclean:
	$(LATEXMK) -C -outdir=$(OUTDIR) $(MAIN).tex
