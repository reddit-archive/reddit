/* block-level tags for passing html blocks through the blender
 */
#define __WITHOUT_AMALLOC 1
#include "cstring.h"
#include "tags.h"

STRING(struct kw) blocktags;


/* define a html block tag
 */
void
mkd_define_tag(char *id, int selfclose)
{
    struct kw *p = &EXPAND(blocktags);

    p->id = id;
    p->size = strlen(id);
    p->selfclose = selfclose;
}


/* case insensitive string sort (for qsort() and bsearch() of block tags)
 */
static int
casort(struct kw *a, struct kw *b)
{
    if ( a->size != b->size )
	return a->size - b->size;
    return strncasecmp(a->id, b->id, b->size);
}


/* stupid cast to make gcc shut up about the function types being
 * passed into qsort() and bsearch()
 */
typedef int (*stfu)(const void*,const void*);


/* sort the list of html block tags for later searching
 */
void
mkd_sort_tags()
{
    qsort(T(blocktags), S(blocktags), sizeof(struct kw), (stfu)casort);
}



/* look for a token in the html block tag list
 */
struct kw*
mkd_search_tags(char *pat, int len)
{
    struct kw key;
    
    key.id = pat;
    key.size = len;
    
    return bsearch(&key, T(blocktags), S(blocktags), sizeof key, (stfu)casort);
}


/* load in the standard collection of html tags that markdown supports
 */
void
mkd_prepare_tags()
{

#define KW(x)	mkd_define_tag(x, 0)
#define SC(x)	mkd_define_tag(x, 1)

    static int populated = 0;

    if ( populated ) return;
    populated = 1;
    
    KW("STYLE");
    KW("SCRIPT");
    KW("ADDRESS");
    KW("BDO");
    KW("BLOCKQUOTE");
    KW("CENTER");
    KW("DFN");
    KW("DIV");
    KW("OBJECT");
    KW("H1");
    KW("H2");
    KW("H3");
    KW("H4");
    KW("H5");
    KW("H6");
    KW("LISTING");
    KW("NOBR");
    KW("UL");
    KW("P");
    KW("OL");
    KW("DL");
    KW("PLAINTEXT");
    KW("PRE");
    KW("TABLE");
    KW("WBR");
    KW("XMP");
    SC("HR");
    SC("BR");
    KW("IFRAME");
    KW("MAP");

    mkd_sort_tags();
} /* mkd_prepare_tags */
