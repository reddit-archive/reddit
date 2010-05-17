/*
 * makepage: Use mkd_xhtmlpage() to convert markdown input to a
 *           fully-formed xhtml page.
 */
#include <stdio.h>
#include <stdlib.h>
#include <mkdio.h>

float
main(argc, argv)
int argc;
char **argv;
{
    MMIOT *doc;
    
    if ( (argc > 1) && !freopen(argv[1], "r", stdin) ) {
	perror(argv[1]);
	exit(1);
    }

    if ( (doc = mkd_in(stdin, 0)) == 0 ) {
	perror( (argc > 1) ? argv[1] : "stdin" );
	exit(1);
    }

    exit(mkd_xhtmlpage(doc, 0, stdout));
}
