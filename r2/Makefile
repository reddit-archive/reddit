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
js_libs              = $(addprefix lib/,json2.js jquery.cookie.js jquery.url.js ui.core.js ui.datepicker.js jquery.flot.js jquery.lazyload.js)
js_sources           = $(js_libs) jquery.reddit.js reddit.js login.js ui.js base.js sponsored.js compact.js blogbutton.js flair.js analytics.js utils.js
js_targets           = button.js jquery.flot.js sponsored.js
localized_js_targets = reddit.js mobile.js
localized_js_outputs = $(localized_js_targets:.js=.*.js)

# CSS targets 
main_css = reddit.css
main_sprite = $(static_dir)/sprite-main.png
compact_css = compact.css
compact_sprite = $(static_dir)/sprite-compact.png
css_targets = $(main_css) $(compact_css) reddit-ie6-hax.css reddit-ie7-hax.css mobile.css

package    = r2
static_dir = $(package)/public/static

SED=sed
CAT=cat
PYTHON=python
JS_COMPRESS = paster run standalone $(package)/lib/js.py -c "build_reddit_js()"
CSS_COMPRESS = $(SED) -e 's/ \+/ /' -e 's/\/\*.*\*\///g' -e 's/: /:/' | grep -v "^ *$$"
UPDATE_NAMES = $(PYTHON) $(package)/lib/static.py

# If admin codebase is install, get its path so that we can build ini
# files against the primary production.ini
PRIVATEREPOS = $(shell $(PYTHON) -c 'exec "try: import r2admin; print r2admin.__path__[0]\nexcept:pass"')

# If reddit-i18n repo is found, use that for r2.pot generation
I18NPATH = $(shell $(PYTHON) -c 'exec "try: import reddit_i18n; print reddit_i18n.__path__[0]\nexcept ImportError: print \"r2/i18n\""')

#------

JSTARGETS   = $(foreach js,  $(js_targets) $(localized_js_targets),  $(static_dir)/$(js))
JSOUTPUTS   = $(foreach js,  $(js_targets) $(localized_js_outputs),  $(static_dir)/$(js))
JSSOURCES   = $(foreach js,  $(js_sources),  $(static_dir)/js/$(js))
CSSTARGETS  = $(foreach css, $(css_targets), $(static_dir)/$(css))
SPRITES     = $(main_sprite) $(compact_sprite)
RTLCSS      = $(CSSTARGETS:.css=-rtl.css)
NAMES = $(static_dir)/names.json

PYX_FILES := $(shell find . -name \*.pyx)
PYXC_FILES := $(PYX_FILES:.pyx=.c)
PYXSO_FILES := $(PYX_FILES:.pyx=.so)

NAMED = $(JSOUTPUTS) $(CSSTARGETS) $(RTLCSS) $(SPRITES)
NAMELINKS = $(patsubst %.css,%.*.css,$(patsubst %.js,%.*.js,$(NAMED)))
GZIPPED     = $(foreach file, $(filter %.js %.css, $(wildcard $(NAMELINKS))) $(static_dir)/js/lib/jquery.js, $(file).gz)

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

.PHONY: 	pyx js css rtl static names i18n clean clean_static clean_pyx all gzip clean_gzip

$(NAMES): $(JSTARGETS) $(CSSTARGETS) $(RTLCSS) $(SPRITES)
	$(UPDATE_NAMES) $(NAMES) $(NAMED)

$(JSTARGETS): $(JSSOURCES)
	$(JS_COMPRESS)

$(main_sprite) $(static_dir)/$(main_css): $(static_dir)/css/$(main_css)
	rm -f $@ # delete symlink so we don't just overwrite the old mangled file
	$(PYTHON) r2/lib/nymph.py $< $(static_dir)/sprite-main.png | $(CSS_COMPRESS) > $@

$(compact_sprite) $(static_dir)/$(compact_css) : $(static_dir)/css/$(compact_css)
	rm -f $@ # delete symlink so we don't just overwrite the old mangled file
	$(PYTHON) r2/lib/nymph.py $< $(static_dir)/sprite-compact.png | $(CSS_COMPRESS) > $@

$(static_dir)/%.css : $(static_dir)/css/%.css
	$(CAT) $< | $(CSS_COMPRESS) > $@

$(RTLCSS):	%-rtl.css : %.css
	$(SED) -e "s/left/>####</g" \
	   -e "s/right/left/g" \
	   -e "s/>####</right/g" \
	   -e "s/\(margin\|padding\):\s*\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)/\1:\2 \5 \4 \3/g" $< > $@

%.c: %.pyx
	cython $<

$(PYXSO_FILES): $(PYXC_FILES)
	python setup.py build_ext --inplace

pyx: 		$(PYXSO_FILES)

static: 	js css rtl

js: 		pyx $(JSTARGETS)

css: 		$(CSSTARGETS) $(SPRITES)

rtl:		$(RTLCSS)

names:		$(NAMES)

# Not part of 'all' target as it doesn't need to be run for the site to work,
# only when r2.pot needs updating
i18n:
	paster run run.ini r2/lib/strings.py -c "print_rand_strings()" > r2/lib/rand_strings.py
	python setup.py extract_messages -o $(I18NPATH)/r2.pot

gzip: $(GZIPPED)

%.gz: %
	gzip -c $< > $@

clean: clean_static clean_pyx clean_gzip
	rm -f $(INIS) r2/lib/rand_strings.py

clean_pyx:
	rm -f $(PYXSO_FILES) $(PYXC_FILES)

clean_static: clean_names
	rm -f $(JSTARGETS) $(JSOUTPUTS) $(CSSTARGETS) $(RTLCSS) $(SPRITES)

clean_names:
	rm -f $(NAMES) $(NAMELINKS) $(static_dir)/*.md5

clean_gzip:
	rm -f $(static_dir)/*.css.gz $(static_dir)/*.js.gz $(static_dir)/js/lib/*.gz
