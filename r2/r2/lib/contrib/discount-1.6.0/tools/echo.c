#include <stdio.h>
#include <string.h>


main(argc, argv)
char **argv;
{
    int nl = 1;
    int i;

    if ( (argc > 1) && (strcmp(argv[1], "-n") == 0) ) {
	++argv;
	--argc;
	nl = 0;
    }

    for ( i=1; i < argc; i++ ) {
	if ( i > 1 ) putchar(' ');
	fputs(argv[i], stdout);
    }
    if (nl) putchar('\n');
}
