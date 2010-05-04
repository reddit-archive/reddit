/*
 * debugging malloc()/realloc()/calloc()/free() that attempts
 * to keep track of just what's been allocated today.
 */

#include <stdio.h>
#include <stdlib.h>

#define MAGIC 0x1f2e3d4c

struct alist { int magic, size; struct alist *next, *last; };

static struct alist list =  { 0, 0, 0, 0 };

static int mallocs=0;
static int reallocs=0;
static int frees=0;

void *
acalloc(int size, int count)
{
    struct alist *ret = calloc(size + sizeof(struct alist), count);

    if ( ret ) {
	ret->magic = MAGIC;
	ret->size = size * count;
	if ( list.next ) {
	    ret->next = list.next;
	    ret->last = &list;
	    ret->next->last = ret;
	    list.next = ret;
	}
	else {
	    ret->last = ret->next = &list;
	    list.next = list.last = ret;
	}
	++mallocs;
	return ret+1;
    }
    return 0;
}


void*
amalloc(int size)
{
    return acalloc(size,1);
}


void
afree(void *ptr)
{
    struct alist *p2 = ((struct alist*)ptr)-1;

    if ( p2->magic == MAGIC ) {
	p2->last->next = p2->next;
	p2->next->last = p2->last;
	++frees;
	free(p2);
    }
    else
	free(ptr);
}


void *
arealloc(void *ptr, int size)
{
    struct alist *p2 = ((struct alist*)ptr)-1;
    struct alist save;

    if ( p2->magic == MAGIC ) {
	save.next = p2->next;
	save.last = p2->last;
	p2 = realloc(p2, sizeof(*p2) + size);

	if ( p2 ) {
	    p2->size = size;
	    p2->next->last = p2;
	    p2->last->next = p2;
	    ++reallocs;
	    return p2+1;
	}
	else {
	    save.next->last = save.last;
	    save.last->next = save.next;
	    return 0;
	}
    }
    return realloc(ptr, size);
}


void
adump()
{
    struct alist *p;


    for ( p = list.next; p && (p != &list); p = p->next ) {
	fprintf(stderr, "allocated: %d byte%s\n", p->size, (p->size==1) ? "" : "s");
	fprintf(stderr, "           [%.*s]\n", p->size, p+1);
    }

    if ( getenv("AMALLOC_STATISTICS") ) {
	fprintf(stderr, "%d malloc%s\n", mallocs, (mallocs==1)?"":"s");
	fprintf(stderr, "%d realloc%s\n", reallocs, (reallocs==1)?"":"s");
	fprintf(stderr, "%d free%s\n", frees, (frees==1)?"":"s");
    }
}
