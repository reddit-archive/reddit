#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "mkdio.h"

typedef struct rd_opts_s {
  const char * target;
  int nofollow;
} rd_opts_t;

char *
cb_flagmaker (const char * text, const int size, void * arg)
{
  rd_opts_t * opts;
  char * rv;
  int rv_size;
  int bytes_written;

#define TARGET_TAG "target="
#define NOFOLLOW " rel='nofollow'"

  opts = (rd_opts_t *) arg;

  if (opts->target == NULL) {
    opts->target = "";
  }

  if (opts->target[0] == '\0') {
    rv_size = 1; /* need room for a \0 */
  } else {
    /* Need to add 2 more, for the surrounding quotes */
    rv_size = sizeof(TARGET_TAG) + strlen(opts->target) + 2;
  }

  if (opts->nofollow) {
    /* We can subtract 1 because the \0 is already accounted for */
    rv_size += sizeof(NOFOLLOW) - 1;
  }

  rv = malloc(rv_size);

  bytes_written = 1 + sprintf (rv, "%s%s%s%s%s",
           opts->target[0] == '\0' ? "" : TARGET_TAG,
           opts->target[0] == '\0' ? "" : "'",
           opts->target,
           opts->target[0] == '\0' ? "" : "'",
           opts->nofollow ? NOFOLLOW : "");

  if (bytes_written > rv_size) {
    fprintf (stderr, "Augh, allocated %d bytes and wrote %d bytes\n",
             rv_size, bytes_written);
    abort();
  }
  return rv;
}

void
reddit_discount_wrap(const char * text, int nofollow, const char * target,
                     void ** v_mmiot, char ** html, int * size)
{
  rd_opts_t opts;
  MMIOT * mmiot;

  opts.target = target;
  opts.nofollow = nofollow;

  mmiot = mkd_string((char *) text, strlen(text), 0);

  mkd_compile(mmiot, MKD_NOHTML | MKD_NOIMAGE | MKD_NOPANTS | MKD_NOHEADER |
                     MKD_NO_EXT | MKD_AUTOLINK | MKD_SAFELINK);

  mkd_e_flags (mmiot, &cb_flagmaker);
  mkd_e_data(mmiot, &opts);

  *size = mkd_document(mmiot, html);
  *v_mmiot = mmiot;
}

void
reddit_discount_cleanup (void * v_mmiot) {
  mkd_cleanup(v_mmiot);
}

