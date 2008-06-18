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

#ifndef __RECOMMEND_MEMCACHE_H__
#define __RECOMMEND_MEMCACHE_H__
#include <iostream>
#include <memcache.h>
#include <string.h>
#include <openssl/md5.h>

char * MD5er(char * in);


class Memcache {
 protected:
  struct memcache *mc;
 public:
  Memcache();
  ~Memcache();
  


  int add_server(char* ip, char* port = "11211") {
    return mc_server_add(mc, ip, port); 
  }

  int add(char* key, void* object, size_t obj_size, time_t expire = 3*86400) {
    int rval;
    char * k = MD5er(key);
    rval =  mc_add(mc, k, strlen(k), 
		   object, obj_size, expire, 0);
    delete[] k;
    return rval;
  }

  int replace(char* key, void* object, size_t obj_size, time_t expire = 3*86400) {
    int rval;
    char * k = MD5er(key);
    rval =  mc_add(mc, k, strlen(k), 
		   object, obj_size, expire, 0);
    delete[] k;
    return rval;
  }

  int set(char* key, void* object, size_t obj_size, 
          time_t expire = 3*86400) {
    int rval;
    char * k = MD5er(key);
    printf("KEY: %s\n", k);
    rval =  mc_set(mc, k, strlen(k), 
                  object, obj_size, expire, 0);
    delete[] k;
    return rval;
  }

  int del(char*key, time_t hold_timer) {
    int rval;
    char * k = MD5er(key);
    rval =  mc_delete(mc, k, strlen(k), hold_timer); 
    delete[] k;
    return rval;
  }

  void* get(char*key) {
    void* rval;
    char * k = MD5er(key);
    rval =  mc_aget(mc, k, strlen(k)); 
    delete[] k;
    return rval;
  }
    
};

extern Memcache mc;

#endif

