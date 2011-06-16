# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
# 
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
# 
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################

# Javascript files to be compressified
js_sources           = jquery.json.js jquery.reddit.js reddit.js base.js ui.core.js ui.datepicker.js sponsored.js jquery.flot.js jquery.lazyload.js compact.js blogbutton.js
js_targets           = button.js jquery.flot.js sponsored.js
localized_js_targets = reddit.js mobile.js
localized_js_outputs = $(localized_js_targets:.js=.*.js)

# CSS targets 
main_css = reddit.css
css_targets = reddit-ie6-hax.css reddit-ie7-hax.css mobile.css spreadshirt.css compact.css 

package    = r2
static_dir = $(package)/public/static

SED=sed
CAT=cat
PYTHON=python2.6
JS_COMPRESS = paster run standalone $(package)/lib/js.py -c "build_reddit_js()"
CSS_COMPRESS = $(SED) -e 's/ \+/ /' -e 's/\/\*.*\*\///g' -e 's/: /:/' | grep -v "^ *$$"
UPDATE_NAMES = $(PYTHON) $(package)/lib/static.py

# If admin codebase is install, get its path so that we can build ini
# files against the primary production.ini
PRIVATEREPOS = $(shell $(PYTHON) -c 'exec "try: import r2admin; print r2admin.__path__[0]\nexcept:pass"')

#------

JSTARGETS   = $(foreach js,  $(js_targets) $(localized_js_targets),  $(static_dir)/$(js))
JSOUTPUTS   = $(foreach js,  $(js_targets) $(localized_js_outputs),  $(static_dir)/$(js))
JSSOURCES   = $(foreach js,  $(js_sources),  $(static_dir)/js/$(js))
CSSTARGETS  = $(foreach css, $(css_targets), $(static_dir)/$(css))
SPRITES     = $(static_dir)/sprite.png
MAINCSS     = $(foreach css, $(main_css), $(static_dir)/$(css))
RTLCSS      = $(CSSTARGETS:.css=-rtl.css) $(MAINCSS:.css=-rtl.css)
NAMES = $(static_dir)/names.json

PYX_FILES := $(shell find . -name \*.pyx)
PYXSO_FILES := $(PYX_FILES:.pyx=.so)

NAMED = $(JSOUTPUTS) $(CSSTARGETS) $(MAINCSS) $(RTLCSS)
NAMELINKS = $(patsubst %.css,%.*.css,$(patsubst %.js,%.*.js,$(NAMED)))

INIUPDATE = $(wildcard *.update)
INIS      = $(INIUPDATE:.update=.ini)

%.ini:	%.update
ifneq (,$(PRIVATEREPOS))
	  ln -sf `pwd`/$< $(PRIVATEREPOS)/..
	  make -C $(PRIVATEREPOS)/.. $@ 
	  ln -sf $(PRIVATEREPOS)/../$@ . 
else
	  ./updateini.py example.ini $< > $@ || rm $@ 
endif


all:	pyx static names $(INIS)

.PHONY: 	pyx js css rtl static names clean clean_static all

$(NAMES): static
	$(UPDATE_NAMES) $(NAMES) $(NAMED)

$(JSTARGETS): $(JSSOURCES)
	$(JS_COMPRESS)

$(CSSTARGETS): 	$(static_dir)/%.css : $(static_dir)/css/%.css
	$(CAT) $< | $(CSS_COMPRESS) > $@

$(MAINCSS):  $(static_dir)/%.css : $(static_dir)/css/%.css
	$(PYTHON) r2/lib/contrib/nymph.py $< | $(CSS_COMPRESS) > $@

$(RTLCSS):	%-rtl.css : %.css
	$(SED) -e "s/left/>####</g" \
	   -e "s/right/left/g" \
	   -e "s/>####</right/g" \
	   -e "s/\(margin\|padding\):\s*\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)/\1:\2 \5 \4 \3/g" $< > $@

$(PYXSO_FILES): %.so : %.pyx
	rm -f $(<:.pyx=.pyc)
	cython $<
	mkdir -p tmp
	PYTHONPATH=tmp $(PYTHON) pyx_setup.py develop -d tmp -b tmp $<
	rm -r tmp

pyx: 		$(PYXSO_FILES)

static: 	js css rtl

js: 		pyx $(JSTARGETS)

css: 		$(CSSTARGETS) $(MAINCSS)

rtl:		$(RTLCSS)

names:		$(NAMES)

clean: clean_static
	rm -f $(PYXSO_FILES) $(INIS)

clean_static: clean_names
	rm -f $(JSOUTPUTS) $(CSSTARGETS) $(SPRITES) $(MAINCSS)

clean_names:
	rm -f $(NAMES) $(NAMELINKS) $(static_dir)/*.md5
