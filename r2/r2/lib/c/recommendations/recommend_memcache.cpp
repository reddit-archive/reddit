/*
* "The contents of this file are subject to the Common Public Attribution
* License Version 1.0. (the "License"); you may not use this file except in
* compliance with the License. You may obtain a copy of the License at
* http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
* License Version 1.1, but Sections 14 and 15 have been added to cover use of
* software over a computer network and provide for limited attribution for the
* Original Developer. In addition, Exhibit A has been modified to be consistent
* with Exhibit B.
* 
* Software distributed under the License is distributed on an "AS IS" basis,
* WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
* the specific language governing rights and limitations under the License.
* 
* The Original Code is Reddit.
* 
* The Original Developer is the Initial Developer.  The Initial Developer of the
* Original Code is CondeNet, Inc.
* 
* All portions of the code written by CondeNet are Copyright (c) 2006-2008
* CondeNet, Inc. All Rights Reserved.
*******************************************************************************/

#include "recommend_memcache.h"

Memcache mc;

Memcache::Memcache() {
  mc = mc_new();
}

Memcache::~Memcache() {
  mc_free(mc);
}


char * MD5er(char * in) {
  char *hexdigest = new char[34];
  unsigned char out[16];
  int i, j;
  
  strcpy(hexdigest, "");
  MD5((unsigned char*)in, strlen((char*)in), out);
  
  for(i = 0; i < 16; i++) {
    short first = short(out[i]) & 0xF;
    short second = short(out[i]) >> 4;
    char foo[2];
    sprintf(foo, "%x%x", second, first);
    strncat(hexdigest, foo, 2);
  }
}

