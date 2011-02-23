#ifndef _MKDIO_D
#define _MKDIO_D

#include <stdio.h>

typedef void MMIOT;

/* line builder for markdown()
 */
MMIOT *mkd_in(FILE*,int);		/* assemble input from a file */
MMIOT *mkd_string(char*,int,int);	/* assemble input from a buffer */

void mkd_basename(MMIOT*,char*);

/* compilation, debugging, cleanup
 */
int mkd_compile(MMIOT*, int);
int mkd_cleanup(MMIOT*);

/* markup functions
 */
int mkd_dump(MMIOT*, FILE*, int, char*);
int markdown(MMIOT*, FILE*, int);
int mkd_line(char *, int, char **, int);
void mkd_string_to_anchor(char *, int, int (*)(int,void*), void*);
int mkd_xhtmlpage(MMIOT*,int,FILE*);

/* header block access
 */
char* mkd_doc_title(MMIOT*);
char* mkd_doc_author(MMIOT*);
char* mkd_doc_date(MMIOT*);

/* compiled data access
 */
int mkd_document(MMIOT*, char**);
int mkd_toc(MMIOT*, char**);
int mkd_css(MMIOT*, char **);
int mkd_xml(char *, int, char **);

/* write-to-file functions
 */
int mkd_generatehtml(MMIOT*,FILE*);
int mkd_generatetoc(MMIOT*,FILE*);
int mkd_generatexml(char *, int,FILE*);
int mkd_generatecss(MMIOT*,FILE*);
#define mkd_style mkd_generatecss
int mkd_generateline(char *, int, FILE*, int);
#define mkd_text mkd_generateline

/* url generator callbacks
 */
typedef char * (*mkd_callback_t)(const char*, const int, void*);
typedef void   (*mkd_free_t)(char*, void*);

void mkd_e_url(void *, mkd_callback_t);
void mkd_e_flags(void *, mkd_callback_t);
void mkd_e_free(void *, mkd_free_t );
void mkd_e_data(void *, void *);

/* version#.
 */
extern char markdown_version[];

/* special flags for markdown() and mkd_text()
 */
#define MKD_NOLINKS	0x0001	/* don't do link processing, block <a> tags  */
#define MKD_NOIMAGE	0x0002	/* don't do image processing, block <img> */
#define MKD_NOPANTS	0x0004	/* don't run smartypants() */
#define MKD_NOHTML	0x0008	/* don't allow raw html through AT ALL */
#define MKD_STRICT	0x0010	/* disable SUPERSCRIPT, RELAXED_EMPHASIS */
#define MKD_TAGTEXT	0x0020	/* process text inside an html tag; no
				 * <em>, no <bold>, no html or [] expansion */
#define MKD_NO_EXT	0x0040	/* don't allow pseudo-protocols */
#define MKD_CDATA	0x0080	/* generate code for xml ![CDATA[...]] */
#define MKD_NOTABLES	0x0400	/* disallow tables */
#define MKD_NOSTRIKETHROUGH 0x0800/* forbid ~~strikethrough~~ */
#define MKD_TOC		0x1000	/* do table-of-contents processing */
#define MKD_1_COMPAT	0x2000	/* compatability with MarkdownTest_1.0 */
#define MKD_AUTOLINK	0x4000	/* make http://foo.com link even without <>s */
#define MKD_SAFELINK	0x8000	/* paranoid check for link protocol */
#define MKD_EMBED	MKD_NOLINKS|MKD_NOIMAGE|MKD_TAGTEXT

/* special flags for mkd_in() and mkd_string()
 */
#define MKD_NOHEADER	0x0100	/* don't process header blocks */
#define MKD_TABSTOP	0x0200	/* expand tabs to 4 spaces */


#endif/*_MKDIO_D*/
