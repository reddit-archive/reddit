/* two template types:  STRING(t) which defines a pascal-style string
 * of element (t) [STRING(char) is the closest to the pascal string],
 * and ANCHOR(t) which defines a baseplate that a linked list can be
 * built up from.   [The linked list /must/ contain a ->next pointer
 * for linking the list together with.]
 */
#ifndef _CSTRING_D
#define _CSTRING_D

#include <string.h>
#include <stdlib.h>

#ifndef __WITHOUT_AMALLOC
# include "amalloc.h"
#endif

/* expandable Pascal-style string.
 */
#define STRING(type)	struct { type *text; int size, alloc; }

#define CREATE(x)	T(x) = (void*)(S(x) = (x).alloc = 0)
#define EXPAND(x)	(S(x)++)[(S(x) < (x).alloc) \
			    ? (T(x)) \
			    : (T(x) = T(x) ? realloc(T(x), sizeof T(x)[0] * ((x).alloc += 100)) \
					   : malloc(sizeof T(x)[0] * ((x).alloc += 100)) )]

#define DELETE(x)	ALLOCATED(x) ? (free(T(x)), S(x) = (x).alloc = 0) \
				     : ( S(x) = 0 )
#define CLIP(t,i,sz)	\
	    ( ((i) >= 0) && ((sz) > 0) && (((i)+(sz)) <= S(t)) ) ? \
	    (memmove(&T(t)[i], &T(t)[i+sz], (S(t)-(i+sz)+1)*sizeof(T(t)[0])), \
		S(t) -= (sz)) : -1

#define RESERVE(x, sz)	T(x) = ((x).alloc > S(x) + (sz) \
			    ? T(x) \
			    : T(x) \
				? realloc(T(x), sizeof T(x)[0] * ((x).alloc = 100+(sz)+S(x))) \
				: malloc(sizeof T(x)[0] * ((x).alloc = 100+(sz)+S(x))))
#define SUFFIX(t,p,sz)	\
	    memcpy(((S(t) += (sz)) - (sz)) + \
		    (T(t) = T(t) ? realloc(T(t), sizeof T(t)[0] * ((t).alloc += sz)) \
				 : malloc(sizeof T(t)[0] * ((t).alloc += sz))), \
		    (p), sizeof(T(t)[0])*(sz))

#define PREFIX(t,p,sz)	\
	    RESERVE( (t), (sz) ); \
	    if ( S(t) ) { memmove(T(t)+(sz), T(t), S(t)); } \
	    memcpy( T(t), (p), (sz) ); \
	    S(t) += (sz)

/* reference-style links (and images) are stored in an array
 */
#define T(x)		(x).text
#define S(x)		(x).size
#define ALLOCATED(x)	(x).alloc

/* abstract anchor type that defines a list base
 * with a function that attaches an element to
 * the end of the list.
 *
 * the list base field is named .text so that the T()
 * macro will work with it.
 */
#define ANCHOR(t)	struct { t *text, *end; }
#define E(t)		((t).end)

#define ATTACH(t, p)	( T(t) ? ( (E(t)->next = (p)), (E(t) = (p)) ) \
			       : ( (T(t) = E(t) = (p)) ) )

typedef STRING(char) Cstring;

extern void Csputc(int, Cstring *);
extern int Csprintf(Cstring *, char *, ...);
extern int Cswrite(Cstring *, char *, int);
extern void Csreparse(Cstring *, char *, int, int);

#endif/*_CSTRING_D*/
