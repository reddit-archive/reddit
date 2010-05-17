/*
 * mkd2html:  parse a markdown input file and generate a web page.
 *
 * usage:  mkd2html [options] filename
 *  or     mkd2html [options] < markdown > html
 *
 *  options
 *         -css css-file
 *         -header line-to-add-to-<HEADER>
 *         -footer line-to-add-before-</BODY>
 *
 * example:
 *
 *   mkd2html -cs /~orc/pages.css syntax
 *     ( read syntax OR syntax.text, write syntax.html )
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
#ifdef HAVE_BASENAME
# ifdef HAVE_LIBGEN_H
#  include <libgen.h>
# else
#  include <unistd.h>
# endif
#endif
#include <stdarg.h>

#include "mkdio.h"
#include "cstring.h"
#include "amalloc.h"

char *pgm = "mkd2html";

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


void
main(argc, argv)
char **argv;
{
    char *h;
    char *source = 0, *dest = 0;
    MMIOT *mmiot;
    int i;
    FILE *input, *output; 
    STRING(char*) css, headers, footers;


    CREATE(css);
    CREATE(headers);
    CREATE(footers);
    pgm = basename(argv[0]);

    while ( argc > 2 ) {
	if ( strcmp(argv[1], "-css") == 0 ) {
	    EXPAND(css) = argv[2];
	    argc -= 2;
	    argv += 2;
	}
	else if ( strcmp(argv[1], "-header") == 0 ) {
	    EXPAND(headers) = argv[2];
	    argc -= 2;
	    argv += 2;
	}
	else if ( strcmp(argv[1], "-footer") == 0 ) {
	    EXPAND(footers) = argv[2];
	    argc -= 2;
	    argv += 2;
	}
    }


    if ( argc > 1 ) {
	char *p, *dot;
	
	source = malloc(strlen(argv[1]) + 6);
	dest   = malloc(strlen(argv[1]) + 6);

	if ( !(source && dest) )
	    fail("out of memory allocating name buffers");

	strcpy(source, argv[1]);
	if (( p = strrchr(source, '/') ))
	    p = source;
	else
	    ++p;

	if ( (input = fopen(source, "r")) == 0 ) {
	    strcat(source, ".text");
	    if ( (input = fopen(source, "r")) == 0 )
		fail("can't open either %s or %s", argv[1], source);
	}
	strcpy(dest, source);

	if (( dot = strrchr(dest, '.') ))
	    *dot = 0;
	strcat(dest, ".html");

	if ( (output = fopen(dest, "w")) == 0 )
	    fail("can't write to %s", dest);
    }
    else {
	input = stdin;
	output = stdout;
    }

    if ( (mmiot = mkd_in(input, 0)) == 0 )
	fail("can't read %s", source ? source : "stdin");

    if ( !mkd_compile(mmiot, 0) )
	fail("couldn't compile input");


    h = mkd_doc_title(mmiot);

    /* print a header */

    fprintf(output,
	"<!doctype html public \"-//W3C//DTD HTML 4.0 Transitional //EN\">\n"
	"<html>\n"
	"<head>\n"
	"  <meta name=\"GENERATOR\" content=\"mkd2html %s\">\n", markdown_version);

    fprintf(output,"  <meta http-equiv=\"Content-Type\"\n"
		   "        content=\"text/html; charset-us-ascii\">");

    for ( i=0; i < S(css); i++ )
	fprintf(output, "  <link rel=\"stylesheet\"\n"
			"        type=\"text/css\"\n"
			"        href=\"%s\" />\n", T(css)[i]);

    if ( h ) {
	fprintf(output,"  <title>");
	mkd_generateline(h, strlen(h), output, 0);
	fprintf(output, "</title>\n");
    }
    for ( i=0; i < S(headers); i++ )
	fprintf(output, "  %s\n", T(headers)[i]);
    fprintf(output, "</head>\n"
		    "<body>\n");

    /* print the compiled body */

    mkd_generatehtml(mmiot, output);

    for ( i=0; i < S(footers); i++ )
	fprintf(output, "%s\n", T(footers)[i]);
    
    fprintf(output, "</body>\n"
		    "</html>\n");
    
    mkd_cleanup(mmiot);
    exit(0);
}
