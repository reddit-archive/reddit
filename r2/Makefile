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

SHELL=/bin/sh
PYTHON=python
SED=sed
CAT=cat
BUILD_DIR=build

.PHONY: clean
all: pyx static ini
clean: clean_pyx clean_i18n clean_static

#################### Cython
PYX_FILES := $(shell find . -name \*.pyx)
PYX_C_FILES := $(PYX_FILES:.pyx=.c)
PYX_SO_FILES := $(PYX_FILES:.pyx=.so)
PYX_BUILDSTAMP := $(BUILD_DIR)/pyx-buildstamp

.PHONY: clean_pyx

pyx: $(PYX_BUILDSTAMP)

$(PYX_C_FILES): %.c: %.pyx
	cython $<

# this won't rebuild pyx if you're a jerk and delete a .so file without deleting the buildstamp
# make clean && make pyx will fix this
$(PYX_BUILDSTAMP): $(PYX_C_FILES)
	$(PYTHON) setup.py build_ext --inplace
	touch $@

clean_pyx:
	rm -f $(PYX_BUILDSTAMP) $(PYX_C_FILES) $(PYX_SO_FILES)

#################### i18n
I18NPATH := $(shell $(PYTHON) -c 'from r2.lib.translation import I18N_PATH; print I18N_PATH')
STRINGS_FILE := r2/lib/strings.py
RAND_STRINGS_FILE := r2/lib/rand_strings.py
POTFILE := $(I18NPATH)/r2.pot

.PHONY: i18n clean_i18n

i18n: $(RAND_STRINGS_FILE)
	$(PYTHON) setup.py extract_messages -o $(POTFILE)

$(RAND_STRINGS_FILE): $(STRINGS_FILE)
	paster run standalone $(STRINGS_FILE) -c "print_rand_strings()" > $(RAND_STRINGS_FILE)

clean_i18n:
	rm -f $(RAND_STRINGS_FILE)

#################### ini files
UPDATE_FILES := $(wildcard *.update)
INIFILES := $(UPDATE_FILES:.update=.ini)

.PHONY: clean_ini

ini: $(INIFILES)

$(INIFILES): %.ini: %.update
	  ./updateini.py example.ini $< > $@ || rm $@ 

clean_ini:
	rm $(INIFILES)

#################### Static Files
STATIC_DIR := r2/public/static

.PHONY: clean_static

static: pyx css js names

clean_static: clean_css clean_js clean_names

#### Stylesheets
CSS_COMPRESS := $(SED) -e 's/ \+/ /' -e 's/\/\*.*\*\///g' -e 's/: /:/' | grep -v "^ *$$"
CSS_SOURCE_DIR := $(STATIC_DIR)/css

SPRITED_STYLESHEETS := reddit.css compact.css
PROCESSED_SPRITED_STYLESHEETS := $(addprefix $(STATIC_DIR)/, $(SPRITED_STYLESHEETS))
SPRITES := $(addprefix $(STATIC_DIR)/, $(patsubst %.css,sprite-%.png, $(SPRITED_STYLESHEETS)))

OTHER_STYLESHEETS := reddit-ie6-hax.css reddit-ie7-hax.css mobile.css
MINIFIED_OTHER_STYLESHEETS := $(addprefix $(STATIC_DIR)/, $(OTHER_STYLESHEETS))

PROCESSED_STYLESHEETS := $(PROCESSED_SPRITED_STYLESHEETS) $(MINIFIED_OTHER_STYLESHEETS)
RTL_STYLESHEETS := $(PROCESSED_STYLESHEETS:.css=-rtl.css)

CSS_OUTPUTS = $(PROCESSED_STYLESHEETS) $(RTL_STYLESHEETS) $(SPRITES)

.PHONY: clean_css

css: $(CSS_OUTPUTS)

$(MINIFIED_OTHER_STYLESHEETS): $(STATIC_DIR)/%.css: $(CSS_SOURCE_DIR)/%.css
	# when static file names are mangled, the original becomes a symlink to the mangled name
	# remove the original file here in case it's a symlink so we don't just rewrite the old file
	rm -f $@
	$(CAT) $< | $(CSS_COMPRESS) > $@

$(STATIC_DIR)/sprite-%.png $(STATIC_DIR)/%.css: $(CSS_SOURCE_DIR)/%.css
	# see above
	rm -f $(STATIC_DIR)/sprite-$*.png $(STATIC_DIR)/$*.css
	$(PYTHON) r2/lib/nymph.py $< $(STATIC_DIR)/sprite-$*.png | $(CSS_COMPRESS) > $(STATIC_DIR)/$*.css

$(RTL_STYLESHEETS): %-rtl.css : %.css
	# see above
	rm -f $@
	$(SED) -e "s/left/>####</g" \
	   -e "s/right/left/g" \
	   -e "s/>####</right/g" \
	   -e "s/\(margin\|padding\):\s*\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)\s\+\([^; ]\+\)/\1:\2 \5 \4 \3/g" $< > $@

clean_css:
	rm -f $(CSS_OUTPUTS)

#### JS
JS_MODULES := $(shell $(PYTHON) r2/lib/js.py enumerate_modules)
JS_MODULE_BUILDSTAMPS := $(foreach module,$(JS_MODULES),$(BUILD_DIR)/$(module)-js-buildstamp)
JS_OUTPUTS := $(shell $(PYTHON) r2/lib/js.py enumerate_outputs)

.PHONY: clean_js

js: $(JS_MODULE_BUILDSTAMPS)

$(JS_OUTPUTS): $(JS_MODULE_BUILDSTAMPS)

define JS_MODULE_TEMPLATE
$(BUILD_DIR)/$(1)-js-buildstamp: $$(shell $(PYTHON) r2/lib/js.py dependencies $(1))
	paster run standalone r2/lib/js.py -c "build_module('$(1)')"
	touch $$@
endef

# apply the module template to each of the modules
# so they source their deps from js.py and build accordingly
$(foreach module,$(JS_MODULES),$(eval $(call JS_MODULE_TEMPLATE,$(module))))

clean_js:
	rm -f $(JS_MODULE_BUILDSTAMPS) $(STATIC_DIR)/*.js

#### name mangling
MANGLEABLE_FILES := $(CSS_OUTPUTS) $(JS_OUTPUTS)
MANGLE_BUILDSTAMP := $(BUILD_DIR)/mangle-buildstamp
NAMES_FILE := $(STATIC_DIR)/names.json
MANGLED_FILES := $(wildcard $(foreach file,$(MANGLEABLE_FILES),$(basename $(file)).*$(suffix $(file))))

.PHONY: clean_names

names: $(MANGLE_BUILDSTAMP)

$(MANGLE_BUILDSTAMP): $(MANGLEABLE_FILES)
	$(PYTHON) r2/lib/static.py $(NAMES_FILE) $(MANGLEABLE_FILES)
	touch $@

clean_names:
	rm -f $(MANGLE_BUILDSTAMP) $(NAMES_FILES) $(MANGLED_FILES)

#### gzip!
GZIPPABLE := $(filter %.css %.js,$(MANGLED_FILES) $(STATIC_DIR)/js/lib/jquery.js)
GZIPPED := $(addsuffix .gzip,$(GZIPPABLE))

.PHONY: clean_gzip

gzip: $(GZIPPED)

$(GZIPPED): %.gzip: %
	gzip -c $< > $@

clean_gzip:
	rm -f $(GZIPPED)
