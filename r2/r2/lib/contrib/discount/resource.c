/* markdown: a C implementation of John Gruber's Markdown markup language.
 *
 * Copyright (C) 2007 David L Parsons.
 * The redistribution terms are provided in the COPYRIGHT file that must
 * be distributed with this source code.
 */
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdlib.h>
#include <time.h>
#include <ctype.h>

#include "config.h"

#include "cstring.h"
#include "markdown.h"
#include "amalloc.h"

/* free a (single) line
 */
void
___mkd_freeLine(Line *ptr)
{
    DELETE(ptr->text);
    free(ptr);
}


/* free a list of lines
 */
void
___mkd_freeLines(Line *p)
{
    if (p->next)
	 ___mkd_freeLines(p->next);
    ___mkd_freeLine(p);
}


/* bye bye paragraph.
 */
void
___mkd_freeParagraph(Paragraph *p)
{
    if (p->next)
	___mkd_freeParagraph(p->next);
    if (p->down)
	___mkd_freeParagraph(p->down);
    if (p->text)
	___mkd_freeLines(p->text);
    if (p->ident)
	free(p->ident);
    free(p);
}


/* bye bye footnote.
 */
void
___mkd_freefootnote(Footnote *f)
{
    DELETE(f->tag);
    DELETE(f->link);
    DELETE(f->title);
}


/* bye bye footnotes.
 */
void
___mkd_freefootnotes(MMIOT *f)
{
    int i;

    if ( f->footnotes ) {
	for (i=0; i < S(*f->footnotes); i++)
	    ___mkd_freefootnote( &T(*f->footnotes)[i] );
	DELETE(*f->footnotes);
	free(f->footnotes);
    }
}


/* initialize a new MMIOT
 */
void
___mkd_initmmiot(MMIOT *f, void *footnotes)
{
    if ( f ) {
	memset(f, 0, sizeof *f);
	CREATE(f->in);
	CREATE(f->out);
	CREATE(f->Q);
	if ( footnotes )
	    f->footnotes = footnotes;
	else {
	    f->footnotes = malloc(sizeof f->footnotes[0]);
	    CREATE(*f->footnotes);
	}
    }
}


/* free the contents of a MMIOT, but leave the object alone.
 */
void
___mkd_freemmiot(MMIOT *f, void *footnotes)
{
    if ( f ) {
	DELETE(f->in);
	DELETE(f->out);
	DELETE(f->Q);
	if ( f->footnotes != footnotes )
	    ___mkd_freefootnotes(f);
	memset(f, 0, sizeof *f);
    }
}


/* free lines up to an barrier.
 */
void
___mkd_freeLineRange(Line *anchor, Line *stop)
{
    Line *r = anchor->next;

    if ( r != stop ) {
	while ( r && (r->next != stop) )
	    r = r->next;
	if ( r ) r->next = 0;
	___mkd_freeLines(anchor->next);
    }
    anchor->next = 0;
}


/* clean up everything allocated in __mkd_compile()
 */
void
mkd_cleanup(Document *doc)
{
    if ( doc && (doc->magic == VALID_DOCUMENT) ) {
	if ( doc->ctx ) {
	    ___mkd_freemmiot(doc->ctx, 0);
	    free(doc->ctx);
	}

	if ( doc->code) ___mkd_freeParagraph(doc->code);
	if ( doc->headers ) ___mkd_freeLines(doc->headers);
	if ( T(doc->content) ) ___mkd_freeLines(T(doc->content));
	memset(doc, 0, sizeof doc[0]);
	free(doc);
    }
}
