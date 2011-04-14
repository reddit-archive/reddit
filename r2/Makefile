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

# Jacascript files to be compressified
js_targets  = jquery.js jquery.json.js jquery.reddit.js reddit.js ui.core.js ui.datepicker.js sponsored.js jquery.flot.js compact.js
# CSS targets 
main_css = reddit.css
css_targets = reddit-ie6-hax.css reddit-ie7-hax.css mobile.css spreadshirt.css compact.css 

SED=sed
CAT=cat
CSS_COMPRESS = $(SED) -e 's/ \+/ /' -e 's/\/\*.*\*\///g' -e 's/: /:/' | grep -v "^ *$$"

package    = r2
static_dir = $(package)/public/static
contrib    = $(package)/lib/contrib

JSCOMPRESS = $(contrib)/jsmin.py

# If admin codebase is install, get its path so that we can build ini
# files against the primary production.ini
PRIVATEREPOS = $(shell python -c 'exec "try: import r2admin; print r2admin.__path__[0]\nexcept:pass"')

#------

JSTARGETS  := $(foreach js,  $(js_targets),  $(static_dir)/$(js))
CSSTARGETS := $(foreach css, $(css_targets), $(static_dir)/$(css))
MAINCSS    := $(foreach css, $(main_css), $(static_dir)/$(css))
RTLCSS      = $(CSSTARGETS:.css=-rtl.css) $(MAINCSS:.css=-rtl.css)

PYX_FILES := $(shell find . -name \*.pyx)
PYXSO_FILES := $(PYX_FILES:.pyx=.so)


MD5S = $(JSTARGETS:=.md5) $(CSSTARGETS:=.md5) $(MAINCSS:=.md5) $(RTLCSS:=.md5)

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


all:	$(JSTARGETS) $(CSSTARGETS) $(MD5S) $(RTLCSS) $(INIS) $(PYXSO_FILES)

.PHONY: 	js css md5 rtl clean all

$(MD5S): 	%.md5 : %
	cat $< | openssl md5 > $@

$(JSTARGETS): 	$(static_dir)/%.js : $(static_dir)/js/%.js
	$(JSCOMPRESS) < $< > $@

$(CSSTARGETS): 	$(static_dir)/%.css : $(static_dir)/css/%.css
	$(CAT) $< | $(CSS_COMPRESS) > $@

$(MAINCSS):  $(static_dir)/%.css : $(static_dir)/css/%.css
	python r2/lib/contrib/nymph.py $< | $(CSS_COMPRESS) > $@

$(RTLCSS):	%-rtl.css : %.css
	$(SED) -e "s/left/>####</g" \
	   -e "s/right/left/g" \
	   -e "s/>####</right/g" \
	   -e "s/\(margin\|padding\):\s*\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)/\1:\2 \5 \4 \3/g" $< > $@

$(PYXSO_FILES): %.so : %.pyx
	rm -f $(<:.pyx=.pyc)
	cython $<
	mkdir -p tmp
	PYTHONPATH=tmp python pyx_setup.py develop -d tmp -b tmp $<
	rm -r tmp


js: 		$(JSTARGETS)

css: 		$(CSSTARGETS)

md5:    	$(MD5S)

rtl:		$(RTLCSS)

clean:
	rm $(JSTARGETS) $(CSSTARGETS) $(MD5S) $(INIS)
