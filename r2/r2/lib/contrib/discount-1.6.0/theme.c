/*
 * theme:  use a template to create a webpage (markdown-style)
 *
 * usage:  theme [-d root] [-p pagename] [-t template] [-o html] [source]
 *
 */
/*
 * Copyright (C) 2007 David L Parsons.
 * The redistribution terms are provided in the COPYRIGHT file that must
 * be distributed with this source code.
 */
#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(HAVE_BASENAME) && defined(HAVE_LIBGEN_H)
#  include <libgen.h>
#endif
#include <unistd.h>
#include <stdarg.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <time.h>
#if HAVE_PWD_H
#  include <pwd.h>
#endif
#include <fcntl.h>
#include <errno.h>
#include <ctype.h>

#include "mkdio.h"
#include "cstring.h"
#include "amalloc.h"

char *pgm = "theme";
char *output = 0;
char *pagename = 0;
char *root = 0;
#if HAVE_PWD_H
struct passwd *me = 0;
#endif
struct stat *infop = 0;

#ifndef HAVE_BASENAME
char *
basename(char *path)
{
    char *p;

    if (( p = strrchr(path, '/') ))
	return 1+p;
    return path;
}
#endif

#ifdef HAVE_FCHDIR
typedef int HERE;
#define NOT_HERE (-1)

#define pushd(d)	open(d, O_RDONLY)

int
popd(HERE pwd)
{
    int rc = fchdir(pwd);
    close(pwd);
    return rc;
}

#else

typedef char* HERE;
#define NOT_HERE 0

HERE
pushd(char *d)
{
    HERE cwd;
    int size;
    
    if ( chdir(d) == -1 )
	return NOT_HERE;

    for (cwd = malloc(size=40); cwd; cwd = realloc(cwd, size *= 2))
	if ( getcwd(cwd, size) )
	    return cwd;

    return NOT_HERE;
}

int
popd(HERE pwd)
{
    if ( pwd ) {
	int rc = chdir(pwd);
	free(pwd);

	return rc;
    }
    return -1;
}
#endif

typedef STRING(int) Istring;

void
fail(char *why, ...)
{
    va_list ptr;

    va_start(ptr,why);
    fprintf(stderr, "%s: ", pgm);
    vfprintf(stderr, why, ptr);
    fputc('\n', stderr);
    va_end(ptr);
    exit(1);
}


/* open_template() -- start at the current directory and work up,
 *                    looking for the deepest nested template. 
 *                    Stop looking when we reach $root or /
 */
FILE *
open_template(char *template)
{
    char *cwd;
    int szcwd;
    HERE here = pushd(".");
    FILE *ret;

    if ( here == NOT_HERE )
	fail("cannot access the current directory");

    szcwd = root ? 1 + strlen(root) : 2;

    if ( (cwd = malloc(szcwd)) == 0 )
	return 0;

    while ( !(ret = fopen(template, "r")) ) {
	if ( getcwd(cwd, szcwd) == 0 ) {
	    if ( errno == ERANGE )
		goto up;
	    break;
	}

	if ( root && (strcmp(root, cwd) == 0) )
	    break;	/* ran out of paths to search */
	else if ( (strcmp(cwd, "/") == 0) || (*cwd == 0) )
	    break;	/* reached / */

    up: if ( chdir("..") == -1 )
	    break;
    }
    free(cwd);
    popd(here);
    return ret;
} /* open_template */


static Istring inbuf;
static int psp;

static int
prepare(FILE *input)
{
    int c;

    CREATE(inbuf);
    psp = 0;
    while ( (c = getc(input)) != EOF )
	EXPAND(inbuf) = c;
    fclose(input);
    return 1;
}

static int
pull()
{
    return psp < S(inbuf) ? T(inbuf)[psp++] : EOF;
}

static int
peek(int offset)
{
    int pos = (psp + offset)-1;

    if ( pos >= 0 && pos < S(inbuf) )
	return T(inbuf)[pos];

    return EOF;
}

static int
shift(int shiftwidth)
{
    psp += shiftwidth;
    return psp;
}

static int*
cursor()
{
    return T(inbuf) + psp;
}


static int
thesame(int *p, char *pat)
{
    int i;

    for ( i=0; pat[i]; i++ ) {
	if ( pat[i] == ' ' ) {
	    if ( !isspace(peek(i+1)) ) {
		return 0;
	    }
	}
	else if ( tolower(peek(i+1)) != pat[i] ) {
	    return 0;
	}
    }
    return 1;
}


static int
istag(int *p, char *pat)
{
    int c;

    if ( thesame(p, pat) ) {
	c = peek(strlen(pat)+1);
	return (c == '>' || isspace(c));
    }
    return 0;
}


/* finclude() includes some (unformatted) source
 */
static void
finclude(MMIOT *doc, FILE *out, int flags)
{
    int c;
    Cstring include;
    FILE *f;

    CREATE(include);

    while ( (c = pull()) != '(' )
	;

    while ( (c=pull()) != ')' && c != EOF )
	EXPAND(include) = c;

    if ( c != EOF ) {
	EXPAND(include) = 0;
	S(include)--;

	if (( f = fopen(T(include), "r") )) {
	    while ( (c = getc(f)) != EOF )
		putc(c, out);
	    fclose(f);
	}
    }
    DELETE(include);
}


/* fdirname() prints out the directory part of a path
 */
static void
fdirname(MMIOT *doc, FILE *output, int flags)
{
    char *p;

    if ( pagename && (p = basename(pagename)) )
	fwrite(pagename, strlen(pagename)-strlen(p), 1, output);
}


/* fbasename() prints out the file name part of a path
 */
static void
fbasename(MMIOT *doc, FILE *output, int flags)
{
    char *p;

    if ( pagename ) {
	p = basename(pagename);

	if ( !p )
	    p = pagename;

	if ( p )
	    fwrite(p, strlen(p), 1, output);
    }
}


/* ftitle() prints out the document title
 */
static void
ftitle(MMIOT *doc, FILE* output, int flags)
{
    char *h;
    if ( (h = mkd_doc_title(doc)) == 0 && pagename )
	h = pagename;

    if ( h )
	mkd_generateline(h, strlen(h), output, flags);
}


/* fdate() prints out the document date
 */
static void
fdate(MMIOT *doc, FILE *output, int flags)
{
    char *h;

    if ( (h = mkd_doc_date(doc)) || ( infop && (h = ctime(&infop->st_mtime)) ) )
	mkd_generateline(h, strlen(h), output, flags|MKD_TAGTEXT);
}


/* fauthor() prints out the document author
 */
static void
fauthor(MMIOT *doc, FILE *output, int flags)
{
    char *h = mkd_doc_author(doc);

#if HAVE_PWD_H
    if ( (h == 0) && me )
	h = me->pw_gecos;
#endif

    if ( h )
	mkd_generateline(h, strlen(h), output, flags);
}


/* fversion() prints out the document version
 */
static void
fversion(MMIOT *doc, FILE *output, int flags)
{
    fwrite(markdown_version, strlen(markdown_version), 1, output);
}


/* fbody() prints out the document
 */
static void
fbody(MMIOT *doc, FILE *output, int flags)
{
    mkd_generatehtml(doc, output);
}

/* ftoc() prints out the table of contents
 */
static void
ftoc(MMIOT *doc, FILE *output, int flags)
{
    mkd_generatetoc(doc, output);
}

/* fstyle() prints out the document's style section
 */
static void
fstyle(MMIOT *doc, FILE *output, int flags)
{
    mkd_generatecss(doc, output);
}


#define INTAG 0x01
#define INHEAD 0x02
#define INBODY 0x04

/*
 * theme expansions we love:
 *   <?theme date?>	-- the document date (file or header date)
 *   <?theme title?>	-- the document title (header title or document name)
 *   <?theme author?>	-- the document author (header author or document owner)
 *   <?theme version?>  -- the version#
 *   <?theme body?>	-- the document body
 *   <?theme source?>	-- the filename part of the document name
 *   <?theme dir?>	-- the directory part of the document name
 *   <?theme html?>	-- the html file name
 *   <?theme style?>	-- document-supplied style blocks
 *   <?theme include(file)?> -- include a file.
 */
static struct _keyword {
    char *kw;
    int where;
    void (*what)(MMIOT*,FILE*,int);
} keyword[] = { 
    { "author?>",  0xffff, fauthor },
    { "body?>",    INBODY, fbody },
    { "toc?>",     INBODY, ftoc },
    { "date?>",    0xffff, fdate },
    { "dir?>",     0xffff, fdirname },
    { "include(",  0xffff, finclude },
    { "source?>",  0xffff, fbasename },
    { "style?>",   INHEAD, fstyle },
    { "title?>",   0xffff, ftitle },
    { "version?>", 0xffff, fversion },
};
#define NR(x)	(sizeof x / sizeof x[0])


/* spin() - run through the theme template, looking for <?theme expansions
 */
void
spin(FILE *template, MMIOT *doc, FILE *output)
{
    int c;
    int *p;
    int flags;
    int where = 0x0;
    int i;

    prepare(template);

    while ( (c = pull()) != EOF ) {
	if ( c == '<' ) {
	    if ( peek(1) == '!' && peek(2) == '-' && peek(3) == '-' ) {
		fputs("<!--", output);
		shift(3);
		do {
		    putc(c=pull(), output);
		} while ( ! (c == '-' && peek(1) == '-' && peek(2) == '>') );
	    }
	    else if ( (peek(1) == '?') && thesame(cursor(), "?theme ") ) {
		shift(strlen("?theme "));

		while ( ((c = pull()) != EOF) && isspace(c) )
		    ;

		shift(-1);
		p = cursor();

		if ( where & INTAG ) 
		    flags = MKD_TAGTEXT;
		else if ( where & INHEAD )
		    flags = MKD_NOIMAGE|MKD_NOLINKS;
		else
		    flags = 0;

		for (i=0; i < NR(keyword); i++)
		    if ( thesame(p, keyword[i].kw) ) {
			if ( keyword[i].where & where )
			    (*keyword[i].what)(doc,output,flags);
			break;
		    }

		while ( (c = pull()) != EOF && (c != '?' && peek(1) != '>') )
		    ;
		shift(1);
	    }
	    else
		putc(c, output);

	    if ( istag(cursor(), "head") ) {
		where |= INHEAD;
		where &= ~INBODY;
	    }
	    else if ( istag(cursor(), "body") ) {
		where &= ~INHEAD;
		where |= INBODY;
	    }
	    where |= INTAG;
	    continue;
	}
	else if ( c == '>' )
	    where &= ~INTAG;

	putc(c, output);
    }
} /* spin */


void
main(argc, argv)
char **argv;
{
    char *template = "page.theme";
    char *source = "stdin";
    FILE *tmplfile;
    int opt;
    int force = 0;
    MMIOT *doc;
    struct stat sourceinfo;

    opterr=1;
    pgm = basename(argv[0]);

    while ( (opt=getopt(argc, argv, "fd:t:p:o:V")) != EOF ) {
	switch (opt) {
	case 'd':   root = optarg;
		    break;
	case 'p':   pagename = optarg;
		    break;
	case 'f':   force = 1;
		    break;
	case 't':   template = optarg;
		    break;
	case 'o':   output = optarg;
		    break;
	case 'V':   printf("theme+discount %s\n", markdown_version);
		    exit(0);
	default:    fprintf(stderr, "usage: %s [-V] [-d dir] [-p pagename] [-t template] [-o html] [file]\n", pgm);
		    exit(1);
	}
    }

    tmplfile = open_template(template);

    argc -= optind;
    argv += optind;


    if ( argc > 0 ) {
	int added_text=0;

	if ( (source = malloc(strlen(argv[0]) + strlen("/index.text") + 1)) == 0 )
	    fail("out of memory allocating name buffer");

	strcpy(source,argv[0]);
	if ( (stat(source, &sourceinfo) == 0) && S_ISDIR(sourceinfo.st_mode) )
	    strcat(source, "/index");

	if ( !freopen(source, "r", stdin) ) {
	    strcat(source, ".text");
	    added_text = 1;
	    if ( !freopen(source, "r", stdin) )
		fail("can't open either %s or %s", argv[0], source);
	}

	if ( !output ) {
	    char *p, *q;
	    output = alloca(strlen(source) + strlen(".html") + 1);

	    strcpy(output, source);

	    if (( p = strchr(output, '/') ))
		q = strrchr(p+1, '.');
	    else
		q = strrchr(output, '.');

	    if ( q )
		*q = 0;
	    strcat(q, ".html");
	}
    }
    if ( output ) {
	if ( force )
	    unlink(output);
	if ( !freopen(output, "w", stdout) )
	    fail("can't write to %s", output);
    }

    if ( !pagename )
	pagename = source;

    if ( (doc = mkd_in(stdin, 0)) == 0 )
	fail("can't read %s", source ? source : "stdin");

    if ( fstat(fileno(stdin), &sourceinfo) == 0 )
	infop = &sourceinfo;

#if HAVE_GETPWUID
    me = getpwuid(infop ? infop->st_uid : getuid());

    if ( (root = strdup(me->pw_dir)) == 0 )
	fail("out of memory");
#endif

    if ( !mkd_compile(doc, MKD_TOC) )
	fail("couldn't compile input");

    if ( tmplfile )
	spin(tmplfile,doc,stdout);
    else
	mkd_generatehtml(doc, stdout);

    mkd_cleanup(doc);
    exit(0);
}
