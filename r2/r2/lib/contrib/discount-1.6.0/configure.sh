#! /bin/sh

# local options:  ac_help is the help message that describes them
# and LOCAL_AC_OPTIONS is the script that interprets them.  LOCAL_AC_OPTIONS
# is a script that's processed with eval, so you need to be very careful to
# make certain that what you quote is what you want to quote.

# load in the configuration file
#
ac_help='--enable-dl-tag		Use the DL tag extension
--enable-pandoc-header	Use pandoc-style header blocks
--enable-superscript	A^B becomes A<sup>B</sup>
--enable-amalloc	Enable memory allocation debugging
--relaxed-emphasis	underscores aren'\''t special in the middle of words
--with-tabstops=N	Set tabstops to N characters (default is 4)
--enable-div		Enable >%id% divisions
--enable-alpha-list	Enable (a)/(b)/(c) lists
--enable-all-features	Turn on all stable optional features'

LOCAL_AC_OPTIONS='
set=`locals $*`;
if [ "$set" ]; then
    eval $set
    shift 1
else
    ac_error=T;
fi'

locals() {
    K=`echo $1 | $AC_UPPERCASE`
    case "$K" in
    --RELAXED-EMPHAS*)
		echo RELAXED_EMPHASIS=T
		;;
    --ENABLE-ALL|--ENABLE-ALL-FEATURES)
		echo WITH_DL_TAG=T
		echo RELAXED_EMPHASIS=T
		echo WITH_PANDOC_HEADER=T
		echo WITH_SUPERSCRIPT=T
		echo WITH_AMALLOC=T
		echo WITH_DIV=T
		#echo WITH_ALPHA_LIST=T
		;;
    --ENABLE-*)	enable=`echo $K | sed -e 's/--ENABLE-//' | tr '-' '_'`
		echo WITH_${enable}=T ;;
    esac
}

TARGET=markdown
. ./configure.inc

AC_INIT $TARGET

AC_PROG_CC

case "$AC_CC $AC_CFLAGS" in
*-Wall*)    AC_DEFINE 'while(x)' 'while( (x) != 0 )'
	    AC_DEFINE 'if(x)' 'if( (x) != 0 )' ;;
esac

AC_PROG ar || AC_FAIL "$TARGET requires ar"
AC_PROG ranlib

AC_C_VOLATILE
AC_C_CONST
AC_SCALAR_TYPES
AC_CHECK_BASENAME

AC_CHECK_HEADERS sys/types.h pwd.h && AC_CHECK_FUNCS getpwuid

if AC_CHECK_FUNCS srandom; then
    AC_DEFINE 'INITRNG(x)' 'srandom((unsigned int)x)'
elif AC_CHECK_FUNCS srand; then
    AC_DEFINE 'INITRNG(x)' 'srand((unsigned int)x)'
else
    AC_DEFINE 'INITRNG(x)' '(void)1'
fi

if AC_CHECK_FUNCS 'bzero((char*)0,0)'; then
    : # Yay
elif AC_CHECK_FUNCS 'memset((char*)0,0,0)'; then
    AC_DEFINE 'bzero(p,s)' 'memset(p,s,0)'
else
    AC_FAIL "$TARGET requires bzero or memset"
fi

if AC_CHECK_FUNCS random; then
    AC_DEFINE 'COINTOSS()' '(random()&1)'
elif AC_CHECK_FUNCS rand; then
    AC_DEFINE 'COINTOSS()' '(rand()&1)'
else
    AC_DEFINE 'COINTOSS()' '1'
fi

if AC_CHECK_FUNCS strcasecmp; then
    :
elif AC_CHECK_FUNCS stricmp; then
    AC_DEFINE strcasecmp stricmp
else
    AC_FAIL "$TARGET requires either strcasecmp() or stricmp()"
fi

if AC_CHECK_FUNCS strncasecmp; then
    :
elif AC_CHECK_FUNCS strnicmp; then
    AC_DEFINE strncasecmp strnicmp
else
    AC_FAIL "$TARGET requires either strncasecmp() or strnicmp()"
fi

if AC_CHECK_FUNCS fchdir || AC_CHECK_FUNCS getcwd ; then
    AC_SUB 'THEME' ''
else
    AC_SUB 'THEME' '#'
fi

if [ -z "$WITH_TABSTOPS" ]; then
    TABSTOP=4
elif [ "$WITH_TABSTOPS" -eq 1 ]; then
    TABSTOP=8
else
    TABSTOP=$WITH_TABSTOPS
fi
AC_DEFINE 'TABSTOP' $TABSTOP
AC_SUB    'TABSTOP' $TABSTOP

test -z "$WITH_SUPERSCRIPT" || AC_DEFINE 'SUPERSCRIPT'	1
test -z "$RELAXED_EMPHASIS" || AC_DEFINE 'RELAXED_EMPHASIS'	1
test -z "$WITH_DIV"         || AC_DEFINE 'DIV_QUOTE'	1
test -z "$WITH_ALPHA_LIST"  || AC_DEFINE 'ALPHA_LIST'	1


if [ "$WITH_AMALLOC" ]; then
    AC_DEFINE	'USE_AMALLOC'	1
    AC_SUB	'AMALLOC'	'amalloc.o'
else
    AC_SUB	'AMALLOC'	''
fi

if [ "$RELAXED_EMPHASIS" -o "$WITH_SUPERSCRIPT" ]; then
    AC_SUB      'STRICT'	''
else
    AC_SUB	'STRICT'	'.\"'
fi


[ "$OS_FREEBSD" -o "$OS_DRAGONFLY" ] || AC_CHECK_HEADERS malloc.h

[ "$WITH_DL_TAG" ] && AC_DEFINE 'DL_TAG_EXTENSION' '1'
[ "$WITH_PANDOC_HEADER" ] && AC_DEFINE 'PANDOC_HEADER' '1'

AC_OUTPUT Makefile version.c markdown.1
