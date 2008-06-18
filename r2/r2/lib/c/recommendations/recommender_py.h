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

#ifndef __RECOMMENDER_PY_H__
#define __RECOMMENDER_PY_H__

#include "Recommender.h"
#include "recommend_memcache.h"

class RecommenderEngine {
 protected:
  Recommender *rec;
 public:
  RecommenderEngine() : rec(NULL) { }

    void add_mc_server(char *ip, char* port) {
      mc.add_server(ip, port);
    }

    void init(bool verbose = true,  int age = 3, int mod_age = 30,
              int nclusters = 40, int niterations = 10, float fudge = 0.,
              bool storeModded = true) {
    rec = new Recommender(nclusters, niterations, 
                          verbose, fudge, age, mod_age, storeModded);
  }

  void load(char* file) {
    if(rec) delete rec;
    rec = new Recommender(file);
  }
  
  void refresh(bool restart) {
    if(!rec) init();
    rec->refresh(restart);
  }

};


#endif
