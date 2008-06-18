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

#ifndef _RECOMMENDER_H_
#define _RECOMMENDER_H_
#include <vector>
#include <map>
#include <fstream>
#include "SparseMatrix.h"
#include "articles.h"
#include "ModsTable.h"
#include "User.h"
using namespace std;

class Clusters {
protected:
  ModsTable *mods;
  vector<vector<int> > clusters;
  vector<User> centroids;

  map<int, int> cluster_lookup;
  vector<float> spread;
  
  int nclusters;

  void compute_centroids();
  int recompute_centroid(int i);

  void GrahamSchmidt(int);

public:
  Clusters(int _nclusters, ModsTable &_mods) {
    nclusters= _nclusters;
    mods = &_mods;
  }
    
  int operator()(int user, bool tryAgain = false);

  void add(vector<int>& users);

  void add(int u, bool tryAgain = false) {
    int group = (*this)(u, tryAgain);
    clusters[group].push_back(u);
    cluster_lookup[u] = group;
  }

  void generate(RecTable&, 
                int nreclusters = 1, 
                int niterations = 10,
                bool GrahamSchmidt = true) ;
    
  void clear();

  int size(int i = -1) {
    if( i < 0)
      return nclusters; 
    else if(i < nclusters)
      return clusters[i].size();
    return -1;
  }

  float guess(int user, int article) {
    if(cluster_lookup.find(user) != cluster_lookup.end()) {
      int i = cluster_lookup[user];
      if(i >= 0 && i < nclusters && centroids[i].has_key(article))
        return centroids[i][article];
    }
    return 0;
  }
  
  bool has_user(int user) { 
    return cluster_lookup.find(user) != cluster_lookup.end(); 
  }
  
  vector<int>::iterator begin(int i) {
    return clusters[i].begin();
  }

  vector<int>::iterator end(int i) {
    return clusters[i].end();
  }

  vector<pair<int, float> > cluster_distances(int user);

};


class Recommender {
protected:
  RecTable dbs_cluster;

  Clusters cl;

  RecentArticles Articles;
  bool storeModdedArticles;

  ModsTable mods;

  map<int, vector<pair<int, float> > > sim_users;

  int niterations;
  bool verbose;
  double fudge;
  int age;
	
  ofstream user_to_cluster_mapping; 

  const static int user_cutoff = 100;

 protected:

  void who_did_we_forget(ModsTable& recs);
  void how_are_we_doing(RecTable& recs, ModsTable& all_recs);

  double user_preference(int user, int article);
  vector<pair<int, float> > &similar_users(int user, bool = false, bool = false);
  
  void cache_recommendations(set<int>&, set<int>&, bool = false);
  
  void add_articles(vector<int>& articles);

  void check_cache();

public:

  Recommender(char* fileName);

  Recommender( int nclusters = 40, int niterations = 10, 
               bool verbose = true, float fudge = 0, int age = 3, 
               int modAge = 30, bool storeModded = true);

  void init(int nclusters = 40, int niterations = 10, 
            bool verbose = true, float fudge = 0, int age = 3, bool storeModded = true);
  
  //void reinit(bool start_over = false);
  void refresh(bool = false);
  float predict(int user, int article, bool tryAgain = false);

  //  FILE* toFile(FILE*);
  //  void fromFile(FILE*);
};

#endif

