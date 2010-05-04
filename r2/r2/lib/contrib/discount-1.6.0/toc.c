/*
 * toc -- spit out a table of contents based on header blocks
 *
 * Copyright (C) 2008 Jjgod Jiang, David L Parsons.
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

/* write an header index
 */
int
mkd_toc(Document *p, char **doc)
{
    Paragraph *tp, *srcp;
    int last_hnumber = 0;
    Cstring res;
    
    CREATE(res);
    RESERVE(res, 100);

    *doc = 0;

    if ( !(p && p->ctx) ) return -1;
    if ( ! (p->ctx->flags & TOC) ) return 0;

    for ( tp = p->code; tp ; tp = tp->next ) {
	if ( tp->typ == SOURCE ) {
	    for ( srcp = tp->down; srcp; srcp = srcp->next ) {
		if ( srcp->typ == HDR && srcp->text ) {
	    
		    if ( last_hnumber == srcp->hnumber )
			Csprintf(&res,  "%*s</li>\n", srcp->hnumber, "");
		    else while ( last_hnumber > srcp->hnumber ) {
			Csprintf(&res, "%*s</li>\n%*s</ul>\n",
					 last_hnumber, "",
					 last_hnumber-1,"");
			--last_hnumber;
		    }

		    while ( srcp->hnumber > last_hnumber ) {
			Csprintf(&res, "\n%*s<ul>\n", srcp->hnumber, "");
			++last_hnumber;
		    }
		    Csprintf(&res, "%*s<li><a href=\"#", srcp->hnumber, "");
		    mkd_string_to_anchor(T(srcp->text->text), S(srcp->text->text), Csputc, &res);
		    Csprintf(&res, "\">");
		    Csreparse(&res, T(srcp->text->text), S(srcp->text->text), 0);
		    Csprintf(&res, "</a>");
		}
	    }
        }
    }

    while ( last_hnumber > 0 ) {
	Csprintf(&res, "%*s</li>\n%*s</ul>\n",
			last_hnumber, "", last_hnumber, "");
	--last_hnumber;
    }
			/* HACK ALERT! HACK ALERT! HACK ALERT! */
    *doc = T(res);	/* we know that a T(Cstring) is a character pointer */
			/* so we can simply pick it up and carry it away, */
    return S(res);	/* leaving the husk of the Ctring on the stack */
			/* END HACK ALERT */
}


/* write an header index
 */
int
mkd_generatetoc(Document *p, FILE *out)
{
    char *buf = 0;
    int sz = mkd_toc(p, &buf);
    int ret = EOF;

    if ( sz > 0 )
	ret = fwrite(buf, sz, 1, out);

    if ( buf ) free(buf);

    return ret;
}
