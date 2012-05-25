#include <stdio.h>
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>

#include <openssl/sha.h>

#include "utils.h"

#define MAX_LINE 2048

int main(int argc, char** argv)
{
    const char* secret;
    secret = getenv("TRACKING_SECRET");
    if (!secret) {
        fprintf(stderr, "TRACKING_SECRET not set\n");
        return 1;
    }

    char input_line[MAX_LINE];
    unsigned char input_hash[SHA_DIGEST_LENGTH];
    unsigned char expected_hash[SHA_DIGEST_LENGTH];
    int secret_length = strlen(secret);

    while (fgets(input_line, MAX_LINE, stdin) != NULL) {
        /* get the fields */
        char *ip, *path, *query, *unique_id;

        split_fields(
            input_line, 
            &ip, 
            &path, 
            &query, 
            &unique_id, 
            NO_MORE_FIELDS
        );

        /* in the query string, grab the fields we want to verify */
        char *id = NULL;
        char *hash = NULL;

        char *key, *value;
        while (parse_query_param(&query, &key, &value) >= 0) {
            if (strcmp(key, "id") == 0) {
                id = value;
            } else if (strcmp(key, "hash") == 0) {
                hash = value;
            }
        }

        if (id == NULL || hash == NULL)
            continue;

        /* decode the params */
        int id_length = url_decode(id);
        if (id_length < 0)
            continue;

        if (url_decode(hash) != 40)
            continue;

        /* turn the expected hash into bytes */
        bool bad_hash = false;
        for (int i = 0; i < SHA_DIGEST_LENGTH; i++) {
            int count = sscanf(&hash[i*2], "%2hhx", &input_hash[i]);
            if (count != 1) {
                bad_hash = true;
                break;
            }
        }

        if (bad_hash)
            continue;

        /* generate the expected hash */
        SHA_CTX ctx;
        int result = 0;

        result = SHA1_Init(&ctx);
        if (result == 0)
            continue;

        if (strcmp("/pixel/of_defenestration.png", path) != 0) {
            /* the IP is not included on adframe tracker hashes */
            result = SHA1_Update(&ctx, ip, strlen(ip));
            if (result == 0)
                continue;
        }

        result = SHA1_Update(&ctx, id, id_length);
        if (result == 0)
            continue;

        result = SHA1_Update(&ctx, secret, secret_length);
        if (result == 0)
            continue;

        result = SHA1_Final(expected_hash, &ctx);
        if (result == 0)
            continue;

        /* check that the hashes match */
        if (memcmp(input_hash, expected_hash, SHA_DIGEST_LENGTH) != 0)
            continue;

        /* split out the fullname and subreddit if necessary */
        char *fullname = id;
        char *subreddit = NULL;

        for (char *c = id; *c != '\0'; c++) {
            if (*c == '-') {
                subreddit = c + 1;
                *c = '\0';
                break;
            }
        }

        /* output stuff! */
        fputs(unique_id, stdout);
        fputc('\t', stdout);

        fputs(path, stdout);
        fputc('\t', stdout);

        fputs(fullname, stdout);
        fputc('\t', stdout);

        if (subreddit != NULL) {
            fputs(subreddit, stdout);
        }

        fputc('\n', stdout);
    }
}
