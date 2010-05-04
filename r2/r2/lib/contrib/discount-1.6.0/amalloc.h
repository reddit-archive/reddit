/*
 * debugging malloc()/realloc()/calloc()/free() that attempts
 * to keep track of just what's been allocated today.
 */
#ifndef AMALLOC_D
#define AMALLOC_D

#include "config.h"

#ifdef USE_AMALLOC

extern void *amalloc(int);
extern void *acalloc(int,int);
extern void *arealloc(void*,int);
extern void afree(void*);
extern void adump();

#define malloc	amalloc
#define	calloc	acalloc
#define realloc	arealloc
#define free	afree

#else

#define adump()	(void)1

#endif

#endif/*AMALLOC_D*/
