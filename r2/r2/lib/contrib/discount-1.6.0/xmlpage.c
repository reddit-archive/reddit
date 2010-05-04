/*
 * xmlpage -- write a skeletal xhtml page
 *
 * Copyright (C) 2007 David L Parsons.
 * The redistribution terms are provided in the COPYRIGHT file that must
 * be distributed with this source code.
 */
#include "config.h"
#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>

#include "cstring.h"
#include "markdown.h"
#include "amalloc.h"


int
mkd_xhtmlpage(Document *p, int flags, FILE *out)
{
    char *title;
    extern char *mkd_doc_title(Document *);
    
    if ( mkd_compile(p, flags) ) {
	fprintf(out, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
	fprintf(out, "<!DOCTYPE html "
		     " PUBLIC \"-//W3C//DTD XHTML 1.0 Strict//EN\""
		     " \"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd\">\n");

	fprintf(out, "<html xmlns=\"http://www.w3.org/1999/xhtml\" xml:lang=\"en\" lang=\"en\">\n");

	fprintf(out, "<head>\n");
	if ( title = mkd_doc_title(p) )
	    fprintf(out, "<title>%s</title>\n", title);
	mkd_generatecss(p, out);
	fprintf(out, "</head>\n");
	
	fprintf(out, "<body>\n");
	mkd_generatehtml(p, out);
	fprintf(out, "</body>\n");
	fprintf(out, "</html>\n");
	
	mkd_cleanup(p);

	return 0;
    }
    return -1;
}
