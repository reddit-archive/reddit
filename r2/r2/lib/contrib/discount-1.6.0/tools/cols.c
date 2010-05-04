#include <stdio.h>
#include <stdlib.h>

main(argc, argv)
char **argv;
{
    register c;
    int xp;
    int width;

    if ( argc != 2 ) {
	fprintf(stderr, "usage: %s width\n", argv[0]);
	exit(1);
    }
    else if ( (width=atoi(argv[1])) < 1 ) {
	fprintf(stderr, "%s: please set width to > 0\n", argv[0]);
	exit(1);
    }


    for ( xp = 1; (c = getchar()) != EOF; xp++ ) {
	while ( c & 0xC0 ) {
	    /* assume that (1) the output device understands utf-8, and
	     *             (2) the only c & 0x80 input is utf-8.
	     */
	    do {
		if ( xp <= width )
		    putchar(c);
	    } while ( (c = getchar()) != EOF && (c & 0x80) && !(c & 0x40) );
	    ++xp;
	}
	if ( c == '\n' )
	    xp = 0;
	if ( xp <= width )
	    putchar(c);
    }
    exit(0);
}
