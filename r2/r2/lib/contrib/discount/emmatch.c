/* markdown: a C implementation of John Gruber's Markdown markup language.
 *
 * Copyright (C) 2010 David L Parsons.
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


/* emmatch: the emphasis mangler that's run after a block
 *          of html has been generated.
 *
 *          It should create MarkdownTest_1.0 (and _1.0.3)
 *          compatable emphasis for non-pathological cases
 *          and it should fail in a standards-compliant way
 *          when someone attempts to feed it junk.
 *
 *          Emmatching is done after the input has been 
 *          processed into a STRING (f->Q) of text and
 *          emphasis blocks.   After ___mkd_emblock() finishes,
 *          it truncates f->Q and leaves the rendered paragraph
 *          if f->out.
 */


/* empair() -- find the NEAREST matching emphasis token (or
 *             subtoken of a 3+ long emphasis token.
 */
static int
empair(MMIOT *f, int first, int last, int match)
{
    
    int i;
    block *begin, *p;

    begin = &T(f->Q)[first];

    for (i=first+1; i <= last; i++) {
	p = &T(f->Q)[i];

	if ( (p->b_type != bTEXT) && (p->b_count <= 0) )
	    continue; /* break? */
	
	if ( p->b_type == begin->b_type ) {
	    if ( p->b_count == match )	/* exact match */
		return i;

	    if ( p->b_count > 2 )	/* fuzzy match */
		return i;
	}
    }
    return 0;
} /* empair */


/* emfill() -- if an emphasis token has leftover stars or underscores,
 *             convert them back into character and append them to b_text.
 */
static void
emfill(block *p)
{
    int j;

    if ( p->b_type == bTEXT )
	return;
	
    for (j=0; j < p->b_count; j++)
	  EXPAND(p->b_text) = p->b_char;
    p->b_count = 0;
} /* emfill */


static void
emclose(MMIOT *f, int first, int last)
{
    int j;

    for (j=first+1; j<last-1; j++)
	emfill(&T(f->Q)[j]);
}


static struct emtags {
    char open[10];
    char close[10];
    int size;
} emtags[] = {  { "<em>" , "</em>", 5 }, { "<strong>", "</strong>", 9 } };


static void emblock(MMIOT*,int,int);


/* emmatch() -- match emphasis for a single emphasis token.
 */
static void
emmatch(MMIOT *f, int first, int last)
{
    block *start = &T(f->Q)[first];
    int e, e2, match;

    switch (start->b_count) {
    case 2: if ( e = empair(f,first,last,match=2) )
		break;
    case 1: e = empair(f,first,last,match=1);
	    break;
    case 0: return;
    default:
	    e = empair(f,first,last,1);
	    e2= empair(f,first,last,2);

	    if ( e2 >= e ) {
		e = e2;
		match = 2;
	    } 
	    else
		match = 1;
	    break;
    }

    if ( e ) {
	/* if we found emphasis to match, match it, recursively call
	 * emblock to match emphasis inside the new html block, add
	 * the emphasis markers for the block, then (tail) recursively
	 * call ourself to match any remaining emphasis on this token.
	 */
	block *end = &T(f->Q)[e];

	end->b_count -= match;
	start->b_count -= match;

	emblock(f, first, e);

	PREFIX(start->b_text, emtags[match-1].open, emtags[match-1].size-1);
	SUFFIX(end->b_post, emtags[match-1].close, emtags[match-1].size);

	emmatch(f, first, last);
    }
} /* emmatch */


/* emblock() -- walk a blocklist, attempting to match emphasis
 */
static void
emblock(MMIOT *f, int first, int last)
{
    int i;
    
    for ( i = first; i <= last; i++ )
	if ( T(f->Q)[i].b_type != bTEXT )
	    emmatch(f, i, last);
    emclose(f, first, last);
} /* emblock */


/* ___mkd_emblock() -- emblock a string of blocks, then concatinate the
 *                     resulting text onto f->out.
 */
void
___mkd_emblock(MMIOT *f)
{
    int i;
    block *p;

    emblock(f, 0, S(f->Q)-1);
    
    for (i=0; i < S(f->Q); i++) {
	p = &T(f->Q)[i];
	emfill(p);
	
	if ( S(p->b_post) ) { SUFFIX(f->out, T(p->b_post), S(p->b_post));
			      DELETE(p->b_post); }
	if ( S(p->b_text) ) { SUFFIX(f->out, T(p->b_text), S(p->b_text));
			      DELETE(p->b_text); }
    }
    
    S(f->Q) = 0;
} /* ___mkd_emblock */
