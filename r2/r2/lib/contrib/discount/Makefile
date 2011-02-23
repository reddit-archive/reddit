CC=cc -I. -L.
AR=/usr/bin/ar
RANLIB=/usr/bin/ranlib

BINDIR=/usr/local/bin
MANDIR=/usr/local/man
LIBDIR=/usr/local/lib
INCDIR=/usr/local/include

PGMS=markdown
SAMPLE_PGMS=mkd2html makepage
SAMPLE_PGMS+= theme
MKDLIB=libmarkdown.a
OBJS=mkdio.o markdown.o dumptree.o generate.o \
     resource.o docheader.o version.o toc.o css.o \
     xml.o Csio.o xmlpage.o basename.o emmatch.o \
     tags.o html5.o 

MAN3PAGES=mkd-callbacks.3 mkd-functions.3 markdown.3 mkd-line.3

all: $(PGMS) $(SAMPLE_PGMS)

install: $(PGMS)
	/usr/bin/install -s -m 755 $(PGMS) $(DESTDIR)/$(BINDIR)
	/usr/bin/install -m 444 $(MKDLIB) $(DESTDIR)/$(LIBDIR)
	/usr/bin/install -m 444 mkdio.h $(DESTDIR)/$(INCDIR)

install.everything: install install.samples install.man

install.samples: $(SAMPLE_PGMS) install
	/usr/bin/install -s -m 755 $(SAMPLE_PGMS) $(DESTDIR)/$(BINDIR)
	/tmp/discount-1.6.8/config.md $(DESTDIR)/$(MANDIR)/man1
	/usr/bin/install -m 444 theme.1 $(DESTDIR)/$(MANDIR)/man1

install.man:
	/tmp/discount-1.6.8/config.md $(DESTDIR)/$(MANDIR)/man3
	/usr/bin/install -m 444 $(MAN3PAGES) $(DESTDIR)/$(MANDIR)/man3
	for x in mkd_line mkd_generateline; do \
	    ( echo '.\"' ; echo ".so man3/mkd-line.3" ) > $(DESTDIR)/$(MANDIR)/man3/$$x.3;\
	done
	for x in mkd_in mkd_string; do \
	    ( echo '.\"' ; echo ".so man3/markdown.3" ) > $(DESTDIR)/$(MANDIR)/man3/$$x.3;\
	done
	for x in mkd_compile mkd_css mkd_generatecss mkd_generatehtml mkd_cleanup mkd_doc_title mkd_doc_author mkd_doc_date; do \
	    ( echo '.\"' ; echo ".so man3/mkd-functions.3" ) > $(DESTDIR)/$(MANDIR)/man3/$$x.3; \
	done
	/tmp/discount-1.6.8/config.md $(DESTDIR)/$(MANDIR)/man7
	/usr/bin/install -m 444 markdown.7 mkd-extensions.7 $(DESTDIR)/$(MANDIR)/man7
	/tmp/discount-1.6.8/config.md $(DESTDIR)/$(MANDIR)/man1
	/usr/bin/install -m 444 markdown.1 $(DESTDIR)/$(MANDIR)/man1

install.everything: install install.man

version.o: version.c VERSION
	$(CC) -DVERSION=\"`cat VERSION`\" -c version.c

markdown: main.o $(MKDLIB)
	$(CC) -o markdown main.o -lmarkdown 

# example programs
theme:  theme.o $(MKDLIB) mkdio.h
	$(CC) -o theme theme.o -lmarkdown 


mkd2html:  mkd2html.o $(MKDLIB) mkdio.h
	$(CC) -o mkd2html mkd2html.o -lmarkdown 

makepage:  makepage.c $(MKDLIB) mkdio.h
	$(CC) -o makepage makepage.c -lmarkdown 

main.o: main.c mkdio.h config.h
	$(CC) -I. -c main.c

$(MKDLIB): $(OBJS)
	$(AR) crv $(MKDLIB) $(OBJS)
	$(RANLIB) $(MKDLIB)

test:	$(PGMS) echo cols
	@for x in tests/*.t; do \
	    sh $$x || exit 1; \
	done

cols:   tools/cols.c config.h
	$(CC) -o cols tools/cols.c
echo:   tools/echo.c config.h
	$(CC) -o echo tools/echo.c
	
clean:
	rm -f $(PGMS) $(SAMPLE_PGMS) *.o $(MKDLIB)

distclean spotless: clean
	rm -f Makefile version.c markdown.1 config.cmd config.sub config.h config.mak config.log config.md

Csio.o: Csio.c cstring.h amalloc.h config.h markdown.h
amalloc.o: amalloc.c
basename.o: basename.c config.h cstring.h amalloc.h markdown.h
css.o: css.c config.h cstring.h amalloc.h markdown.h
docheader.o: docheader.c config.h cstring.h amalloc.h markdown.h
dumptree.o: dumptree.c markdown.h cstring.h amalloc.h config.h
emmatch.o: emmatch.c config.h cstring.h amalloc.h markdown.h
generate.o: generate.c config.h cstring.h amalloc.h markdown.h
main.o: main.c config.h amalloc.h
makepage.o: makepage.c
markdown.o: markdown.c config.h cstring.h amalloc.h markdown.h
mkd2html.o: mkd2html.c config.h mkdio.h cstring.h amalloc.h
mkdio.o: mkdio.c config.h cstring.h amalloc.h markdown.h
resource.o: resource.c config.h cstring.h amalloc.h markdown.h
theme.o: theme.c config.h mkdio.h cstring.h amalloc.h
toc.o: toc.c config.h cstring.h amalloc.h markdown.h
version.o: version.c config.h
xml.o: xml.c config.h cstring.h amalloc.h markdown.h
xmlpage.o: xmlpage.c config.h cstring.h amalloc.h markdown.h
