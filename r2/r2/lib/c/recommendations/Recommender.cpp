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

#include "Recommender.h"
#include <math.h>
#include <algorithm>
#include <vector>
#include <map>
#include <set>
#include <time.h>
#include <iomanip>
#include "recommend_memcache.h"




int pair_comp(pair<int, float>* p1, pair<int, float> *p2) {
  if (p1->first > p2->first) 
    return -1;
  else if (p1->first < p2->first) 
    return 1;
  return 0;
}


vector<pair<int, float> > sort_hash(map<int, float> hash) {
  vector<pair<int, float> > rval(hash.size());
  int i = 0;
  for(map<int, float>::iterator it = hash.begin(); it != hash.end(); 
      it++, i++) {
    rval[i].first = (*it).first;
    rval[i].second = (*it).second;
  }
  sort(rval.begin(), rval.end(), hash_sort_comp());
  return rval;
}

vector<pair<int, float> > sort_hash(User hash) {
  vector<pair<int, float> > rval(hash.size());
  int i = 0;
  User::iterator it;
  for(it = hash.begin(); it != hash.end(); 
      it++, i++) {
    rval[i].first = (*it).first;
    rval[i].second = (*it).second;
  }
  sort(rval.begin(), rval.end(), hash_sort_comp());
  return rval;
}




float general_dist_cos(map<int, float>* i1, map<int, float>* i2) {
  if(i1->size() == 0 || i2->size()== 0)
    return 0;
  map<int, float>::iterator begin1, end1;
  if(i1->size() > i2->size()) {
    begin1 = i2->begin();
    end1 = i2->end();
    i2 = i1;
  }
  else {
    begin1 = i1->begin();
    end1 = i1->end();
  }
  float denom1=0, denom2=0, dist=0;
  for(map<int, float>::iterator i = begin1; i != end1; i++) {
    int key = (*i).first;
    if(i2->count(key) > 0) {
      float part1 = (*i).second;
      float part2 = (*i2)[key];
      dist += part1 * part2;
      denom1 += part1 * part1;
      denom2 += part2 * part2;
    }
  }
  if(denom1*denom2 == 0) return 0;
  return dist/sqrt(denom1*denom2);
}

vector<pair<int, float> > Clusters::cluster_distances(int user) {
  map<int, float> rhash;
  for(int i = 0; i < nclusters; i++) {
    float m = dist(&(*mods)[user], &centroids[i]);
    if(m == 0) continue;
    rhash[i] = m;
  }
  if(rhash.size() == 0)
    for(int i = 0; i < nclusters; i++)
      rhash[i] = centroids[i].size();
  return sort_hash(rhash);
}


int Clusters::operator()(int user, bool tryAgain) 
{
  int ireturn = 0;
  float max_distance = -1e6;
  int i;
  int avoid_i = -1;
  float distance_limit = 1e6;

  // remember what cluster we started in if needs be...
  if(tryAgain && cluster_lookup.find(user) != cluster_lookup.end()) {
    cout << "\t\x1b[35mTrying again -- avoiding ";
    avoid_i = cluster_lookup[user];
    distance_limit = dist(&(*mods)[user], &centroids[avoid_i]);
    cout << avoid_i << " with dist " << distance_limit << endl;
  }
  else if(has_user(user))
    return cluster_lookup[user];

  if(tryAgain)
    cout << "{ ";
  for(i = 0; i < nclusters; i++) {
    float m = dist(&(*mods)[user], &centroids[i]);

    // best to ignore bins which are orthogonal to the user...
    if(!m) continue;
    if(tryAgain) cout << "(" << i << ", " << m << ") ";

    // remember the minimum distance only, provided we aren't trying
    // to avoid one of the indices
    if((i > avoid_i && 
        m == distance_limit && 
        max_distance != distance_limit) || 
       (m > max_distance && m < distance_limit)) {
      max_distance = m;
      ireturn= i;
    }
  }
  if(tryAgain)
    cout << "}";
  if(tryAgain) {
    cout << "\t --> (" << ireturn << ", " << max_distance << ")\x1b[0m" << endl;
  }

  return ireturn;
}


/*
 * For new users added to the reommender after generate_clusters was called
 */
void Clusters::add(vector<int>& users) {
  for(vector<int>::iterator user = users.begin();
      user != users.end(); user++) 
    if(cluster_lookup.count((*user)) == 0) 
      add(*user);
}

/*
 * clears out the cluster list and inits it to contain the first ncluster
 * users.
 */
void Clusters::clear() {
  int i;
  // wipe the existing clusters
  cluster_lookup.clear();
  for(i = 0; i < clusters.size(); i++) {
    clusters[i].clear();
  }
  // initialize the clusters table if not done already
  if(clusters.empty()) 
    for(i = 0; i < nclusters; i++)
      clusters.push_back(vector<int>());


  // ******** wipe sim_users, dbs_cluster, recs
  //  recs.clear();
}


void Clusters::GrahamSchmidt(int verbosity) {
  if(verbosity > 0)
    cout << endl<< "\x1b[31m Attempting Graham-Schmidt on results...\x1b[0m" << endl;
  // Graham Schmidt the results and recurse until done....
  int i;
  for(i = 1; i < nclusters; i++) {
    User *w = &centroids[i];
    for(int j = 0; j < i; j++) {
      User *v = &centroids[j];
      
      double dot_prod = dot(w, v);
      double v_norm = norm(v);
      double w_norm = norm(w);
      
      for(User::iterator v_art = v->begin();
          v_norm && v_art != v->end(); v_art++) {
        int index =   (*v_art).first;
        float v_val = (*v_art).second;
        float w_val = w->has_key(index) ? (*w)[index] : 0.;
        w->add(index, w_val - dot_prod*v_val/(v_norm*v_norm));
      }
    }
  }

  if(verbosity > 0)
    cout << "done" << endl;
  if(verbosity > 1) {
    // dump the self-similarity matrix for the centroids
    cout << endl << "\x1b[31mCentroid Comparison Matrix\x1b[0m" << endl;
    for(i = 0; i < nclusters; i++) {
      printf("\t");
      for(int j = 0; j < nclusters; j++) {
        printf("%6.3f", dist(&centroids[i], &centroids[j], true));
        if(j != nclusters -1)
          printf(",");
      }
      printf("\n");
    }


    // dump the self-similarity matrix for the centroids
    cout << endl << "\x1b[31mCentroid Comparison Matrix (dot)\x1b[0m" << endl;
    for(i = 0; i < nclusters; i++) {
      printf("\t");
      for(int j = 0; j < nclusters; j++) {
        printf("%8.3f", dot(&centroids[i], &centroids[j]));
        if(j != nclusters -1)
          printf(",");
      }
      printf("\n");
    }
  }
}


void Clusters::generate(RecTable & mods0, 
                        int nreclusters,
                        int niterations,
                        bool grahamSchmidt)
{
  bool verbose = true;
  cout << "Generating clusters using " << mods0.size() << " users" << endl;

  int i;
  if(!mods0.size()) {
    cout << "Bad: mods table uninitialized" << endl;
    return;
  }

  if(verbose) {
    cout << "Mods table has " << mods0.size() << " users" << endl;
    cout << "generating clusters" << endl;
  }
  
  clear();

  // default to every user in a random bin
  ModsTable::iterator it;
  for(it = mods0.begin(), i=0;
      it != mods0.end(); i++, it++) {
    if(it == mods0.end()) {
      cout << "Bad: mods table is smaller than the number of clusters" << endl;
      return;
    }
    clusters[i % nclusters].push_back((*it).first);
  }
  
    cout << "Number of clusters: " << clusters.size() << endl;
  // recompute them
  compute_centroids();

 restart_this_sucker:

  if (grahamSchmidt) GrahamSchmidt(1);

  for(int iter = 0; iter < niterations; iter++) {
    time_t start_time = time(NULL);
    
    if(verbose) 
      cout << "Iteration: " << iter << endl;

    // wipe the existing clusters
    clear();

    if(verbose)
      cout << " --> Binning users" << endl;
    int i = 0;
    for(ModsTable::iterator user = mods0.begin();
        user != mods0.end(); user++, i++) 
      add((*user).first);
    
    if(verbose)
      cout << " --> Copying current centroids" << endl;
    // make a copy of the current centroids
    vector<User> oldcentroids;
    for(i = 0; i < nclusters; i++) {
      oldcentroids.push_back(User());
      for(User::iterator article = centroids[i].begin();
          article != centroids[i].end(); article++) {
        oldcentroids[i].add((*article).first,
                            centroids[i][(*article).first]);
      }
    }
    
    // recompute them
    compute_centroids();
    
    float quality=0, difference=0;
    int n_non_zero = 0;
    for(i = 0; i < nclusters; i++) {
      if(clusters[i].empty()) continue;
      n_non_zero++;
      float q = spread[i];
      quality += q;
      //      float d = centroids[i] | oldcentroids[i];
      float d = dist(&centroids[i], &oldcentroids[i], true);
      difference += d;
      int n_per_user = 0;
      for(vector<int>::iterator it = clusters[i].begin();
          it != clusters[i].end(); it++) {
        n_per_user += mods0[(*it)].size();
      }
      if(verbose) 
        cout << "\t( #" << setw(2) << i 
             << ", Q:" << setprecision(3) << setw(7)
             << q << ", Delta:" << setprecision(3) << setw(7) << d 
             << ", Users:" << setw(6) << clusters[i].size() 
             << ", Arts:" << setw(6) << centroids[i].size() 
             << ", Avg # art:" << setw(6) << float(n_per_user)/float(clusters[i].size())
             << ")" 
             << endl;
    }
    if(n_non_zero) {
      quality /= float(n_non_zero);
      difference /= float(n_non_zero);
    }
    if(verbose) 
      cout << "Quality " << quality << ", Difference " << difference 
           << ":  Total time " << difftime(time(NULL), start_time) << "sec" 
           << endl;
    if(difference > .98) break;
  }

  // dump the self-similarity matrix for the centroids
  cout << endl << "\x1b[31mCentroid Comparison Matrix\x1b[0m" << endl;
  for(i = 0; i < nclusters; i++) {
    printf("\t");
    for(int j = 0; j < nclusters; j++) {
      printf("%6.3f", dist(&centroids[i], &centroids[j], true));
      if(j != nclusters -1)
        printf(",");
    }
    printf("\n");
  }

  // dump the self-similarity matrix for the centroids
  cout << endl << "\x1b[31mCentroid Comparison Matrix (dot)\x1b[0m" << endl;
  for(i = 0; i < nclusters; i++) {
    printf("\t");
    for(int j = 0; j < nclusters; j++) {
      printf("%8.3f", dot(&centroids[i], &centroids[j]));
      if(j != nclusters -1)
        printf(",");
    }
    printf("\n");
  }
  // and the corresponding number of entries per cluster
  cout << endl<< "\x1b[31m Article availability\x1b[0m" << endl;
  for(i = 0; i < nclusters; i++) {
    cout << "\tCluster #" << i << ": " << centroids[i].size() 
         << ", Norm: " << norm(&centroids[i]) << endl;
  }

  if(nreclusters --) goto restart_this_sucker;

}




int Clusters::recompute_centroid(int i) {
  int iter_count = 0;
  if(centroids.size() <= i) {
    int original_size = centroids.size();
    for(int j = 0; j <= i - original_size ; j++) {
      centroids.push_back(User());
      spread.push_back(0);
    }
  }


  static map<int, float> rval;
  static map<int, float> nval;
  rval.clear();
  nval.clear();
  vector<int>::iterator user;
  User::iterator art;
  for(user = clusters[i].begin();
      user != clusters[i].end(); user++) {
    for(art = (*mods)[(*user)].begin();
        art != (*mods)[(*user)].end(); art++) {
      iter_count++;
      rval[(*art).first] += (*art).second;
      nval[(*art).first]++;
    }
    
  }
  for(map<int, float>::iterator it = rval.begin();
      it != rval.end(); it++) {
    float val = (*it).second/nval[(*it).first];
    centroids[i].add((*it).first, val);
  }
  
  spread[i] = 0;
  for(user = clusters[i].begin();
      user != clusters[i].end(); user++) 
    spread[i] += dist(&centroids[i], &(*mods)[(*user)]);
  
  if(!clusters[i].empty())
    spread[i] /= clusters[i].size();

  return iter_count;
}



void Clusters::compute_centroids()
{
  time_t start_time = time(NULL);
  bool verbose = true;
  if(verbose) {
    cout << "Computing centroids..." << endl;
    cout << "Wiping old spread and centroid" << endl;
  }

  int i;
  for(i = 0; i < centroids.size(); i++) {
    spread[i] = 0;
    centroids[i].clear();
  }

  if(verbose) cout << "Computing new centroids" << endl;
  int iter_count = 0;
  for(int i = 0; i < nclusters; i++) {
    iter_count += recompute_centroid(i);
  }
  
  if(verbose)
    cout << "Done with centroid recompute.  (" 
         << difftime(time(NULL), start_time)
         << " sec, " << iter_count << " iter)" << endl;
}



// computes the User's actual preference for a given article.
// if the user has modded the article, then the actual
// mod value is returned (weighted by the fudge factor),  
// Otherwise the cluster's preference of the article is returned
// (also weighted by the fudge factor.
double Recommender::user_preference(int user, int article)
{
  //  if(!dbs_cluster.has(user, article)) {
  float rval = 0;
  if(mods.has_key(user)) {
    User &u = mods[user];
    // store the user's actual preference
    if(u.has_key(article))
      rval = (1-fudge)* u[article];
    // add the cluster preference as well
    rval += fudge * cl.guess(user, article);
  }
  return rval; 
}


// given a user and an article, predicts whether the user will like the article
// 
float Recommender::predict(int user, int article, bool tryAgain)
{
  float num = 0, denom = 0;

  vector< pair<int, float> >::iterator user2;
  vector<pair<int, float> > &users = similar_users(user, tryAgain);
  
  for(user2 = users.begin();
      user2 != users.end(); user2++) {
    num += (*user2).second * user_preference((*user2).first, article);
    denom += fabs((*user2).second);
  }
  if(denom == 0) return 0;
    return num/denom;
    
}

vector<pair<int, float> > blank;

// Generates the list of users who are similar to the user u.
// if the user has not yet been binned by the recommender, 
vector<pair<int, float> > &Recommender::similar_users(int user, bool tryAgain, bool redo)
{
  //  if(!sim_users.has_key(user)) {
  if(redo || tryAgain || sim_users.find(user) == sim_users.end()) {

    map<int, float> rhash;
    vector<pair<int, float> > rval;

    int counter= 0;
    if (tryAgain || !cl.has_user(user)) 
      cl(user, tryAgain);

    if (verbose) cout << "\x1b[34m" << user << ": \x1b[0m" ;
    vector<pair<int, float> > i = cl.cluster_distances(user);
    if(i.size() == 0) 
      {
        if (verbose) cout << " --> \x1b[33m\x1b[1mUnclusterable user!!! " 
             << mods[user].size() << " mods available \x1b[0m" << endl;
        return blank;
      }
    float closest_cluster_dist = i[0].second;
    if (verbose) cout << "\x1b[35mMost similar cluster: " ;

    int pos_count = 0;
    int neg_count = 0;
    int n = 0;
    while(n < i.size() && i[n++].second == closest_cluster_dist) {
      if (verbose) cout << i[n-1].first << ", ";
      int j = i[n].first;
      if(j >= 0 && j < cl.size()) {
        vector<int>::iterator user2;
        for(user2 = cl.begin(j); user2 != cl.end(j); user2++) {
          if(user != (*user2) && !mods[user].empty())   {
            User *i1 = &mods[user];
            float dist = 0, denom1 = 0, denom2 = 0;
            for(User::iterator art = i1->begin();
                art != i1->end(); art++) {
              counter ++;
              float part1 = (*art).second;
              float part2;
              part2 = user_preference((*user2), (*art).first);
              dist += part1 * part2;
              denom1 += part1 * part1;
              denom2 += part2 * part2;
            }
            if(dist > 0) pos_count++;
            if(dist < 0) neg_count++;
            if(denom1* denom2 != 0 && dist != 0)
              rhash[(*user2)] = dist/sqrt(denom1*denom2);
          }
        }
      }
    }
    if (verbose) cout << " Q = " << closest_cluster_dist 
         << " -> " << rhash.size() << " users"
         << "( " << pos_count << " similar, " 
         << neg_count << " different)" 
         << "\x1b[0m" << endl;
    if(!rhash.empty()) {
      rval = sort_hash(rhash);
    }
    else {
      cout << " --> \x1b[33m\x1b[1mUnclusterable user!!! Resorting to alternative method\x1b[0m" << endl;  
      int j = i[0].first;
      vector<int>::iterator user2;
      for(user2 = cl.begin(j); user2 != cl.end(j); user2++) {
        rhash[(*user2)] = 0;
      }
      rval = sort_hash(rhash);
    }
    cout << "\t" << rval.size() << " results " << endl;
    sim_users[user] = rval;
  }
  return sim_users[user];
}



void Recommender::check_cache() {
  cout << "checking cache integrity" << endl;
  char buffer[50];
  for(hash<int, User>::iterator user = mods.begin();
      user != mods.end(); user++) {
    sprintf(buffer, "recommend_%d", (*user).first);
    void * store;
    store = mc.get(buffer);
    if(store) {
      cout << "Success: User #" << (*user).first << endl;
      free(store);
    }
    else
      cout << "*Failed: User #" << (*user).first << endl;
  }
}

void Recommender::refresh(bool startFresh) {
  // reload the mods from disk
  RecTable new_mods = mods.newMods(startFresh);
  //  if(!startFresh) 
  hash<int, double> &all_known_articles = Articles(age, startFresh);
  cout << "** Articles total: " << all_known_articles.size() << endl;

  //  how_are_we_doing(new_mods, mods);
  
  /*  if(startFresh) 
    user_to_cluster_mapping.open("user_to_cluster_mapping.csv", 
                                 ofstream::out);
  else
    user_to_cluster_mapping.open("user_to_cluster_mapping.csv", 
    ofstream::out | ofstream::app); */

  if(cl.size() == 0 || startFresh) {
    cout << "Cluster size: " << cl.size() << endl;
    if(startFresh)
      cout << "Forced Regeneration... " << cl.size() << endl;
    cl.generate(mods.the_big_players, 1, niterations, true);
    dbs_cluster.clear();
  }

  //  if(startFresh) how_are_we_doing(new_mods, mods);

// // //   /*  ofstream cluster_file;
// // //   cluster_file.open("cluster_file.out");
// // //   for(int i = 0; i < cl.size(); i++) {
// // //     cluster_file << i << "; [ [";
// // //     for(User::iterator it = centroids[i].begin(i); 
// // //         it != centroids[i].end(); it++) {
// // //       if(it != centroids[i].begin()) 
// // //         cluster_file << ", ";
// // //       cluster_file << "(" << (*it).first << ", " << (*it).second << ")";
// // //     }
// // //     cluster_file << "]";
// // //     for(vector<int>::iterator foo = cl.begin(i); 
// // //         foo != cl.end(i); foo++) {
// // //       cluster_file << ", [";
// // //       for(User::iterator it = mods[(*foo)].begin();
// // //           it != mods[(*foo)].end(); it++) {
// // //         if(it != mods[(*foo)].begin())
// // //           cluster_file << ", ";
// // //         cluster_file << "(" << (*it).first << ", " << (*it).second << ")";
// // //       }
// // //       cluster_file << "]";
// // //     }
    
// // //     cluster_file << "]" << endl;
// // //   }
// // //   cluster_file.close(); */



  // generate a list of users who have been affected by the reload
  // set<int> affectedGroups;
  //  set<int> newArticles;
  set<int> usersToUpdate;

  for(RecTable::iterator it = new_mods.begin();
      it != new_mods.end(); it++) {
    usersToUpdate.insert((*it).first);
    //    affectedGroups.insert(cl((*it).first));
    //    if(!startFresh) 
    //      for(User::iterator art = (*it).second.begin();
    //          art != (*it).second.end(); art++) {
    //        if(all_known_articles.has_key((*art).first))
    //          newArticles.insert((*art).first);
    //      }
  }


  int counter = 0;
  vector<pair<int, float> > sim;
  for(set<int>::iterator u = usersToUpdate.begin(); u != usersToUpdate.end(); u++)
    {
      counter ++;
      sim = similar_users((*u), false, true);
      User uout;
      char buffer[50];
      sprintf(buffer, "recommend_%d", (*u));
      uout.clear();
      float max_num = 0;
      int max_pos = 0;
      for(vector<pair<int, float> >::iterator users = sim.begin();
          users != sim.end(); users++) {
        if((*users).second > max_num)
          max_num = (*users).second;
        if((*users).second > 0)
          max_pos++;
      }
      for(vector<pair<int, float> >::iterator users = sim.begin();
          users != sim.end(); users++) {
        if((*users).second > 0 || max_num == 0 || max_pos <= 1)
          uout.add((*users).first, (*users).second);
      }
      if(uout.size())
        uout.memcachify(buffer);
    }
  cout << "Total users: " << mods.the_big_players.size() << " important, " 
       << counter << " not, " << mods.size() << " total" << endl;
    //    exit(0);
           
//   if(startFresh) {
//     newArticles.cOBlear();
//     for(hash<int, double>::iterator foo = all_known_articles.begin();
//         foo != all_known_articles.end(); foo++)
//       newArticles.insert((*foo).first);
//   }

//   set<int> usersToUpdate;
//   for(set<int>::iterator affectedi = affectedGroups.begin();
//       affectedi != affectedGroups.end(); affectedi++) 
//     usersToUpdate.insert(cl.begin(*affectedi),
//                          cl.end(*affectedi));
//   cout << "Updating " << usersToUpdate.size() << " users on "
//        << newArticles.size() << " articles" << endl;

//   if(!newArticles.empty() && !usersToUpdate.empty())
//     cache_recommendations(usersToUpdate, newArticles, startFresh);

//   user_to_cluster_mapping.close();

//   who_did_we_forget(mods);
}

void Recommender::who_did_we_forget(ModsTable& recs) 
{
  FILE *f = fopen("how_we_are_doing.out", "a");
  for(RecTable::iterator ri = recs.begin();
      ri != recs.end(); ri++) {
    char buffer[50];
    sprintf(buffer, "recommend_%d", (*ri).first);
    User u;
    u.clear();
    u.decachify(buffer);
    if(u.size() == 0) {
      char buffer2[500];
      sprintf(buffer2, "Missed: %d (%d mods)\n", (*ri).first, (*ri).second.size());
      //      printf(buffer2);
      fprintf(f, buffer2);
    }
  }
  fclose(f);
}


void Recommender::how_are_we_doing(RecTable& recs, ModsTable& all_mods) 
{
  cout << "Checking to see how we are doing..." << endl;
  
  const int max_num = 20;
  int num_up_right[max_num],
    num_up_wrong[max_num],
    num_down_right[max_num],
    num_down_wrong[max_num],
    no_guess[max_num],
    total_num[max_num];
  int nclusters = cl.size();

  int *num_up_right_cluster = new int[nclusters+1],
    *num_up_wrong_cluster= new int[nclusters+1],
    *num_down_right_cluster = new int[nclusters+1],
    *num_down_wrong_cluster= new int[nclusters+1],
    *no_guess_cluster= new int[nclusters+1],
    *total_num_cluster= new int[nclusters+1];

  for(int i = 0; i < max_num; i++) {
    num_up_right[i] = 0;
    num_up_wrong[i] = 0;
    num_down_right[i] = 0;
    num_down_wrong[i] = 0;
    no_guess[i] = 0;
    total_num[i] = 0;
  }

  for(int i = 0; i < nclusters+1; i++) {
    num_up_right_cluster[i] = 0;
    num_up_wrong_cluster[i] = 0;
    num_down_right_cluster[i] = 0;
    num_down_wrong_cluster[i] = 0;
    no_guess_cluster[i] = 0;
    total_num_cluster[i] = 0;
  }


  int mod_count = 0;

  for(RecTable::iterator ri = recs.begin();
      ri != recs.end(); ri++) {
    char buffer[50];
    sprintf(buffer, "recommend_%d", (*ri).first);
    User u;
    u.clear();
    u.decachify(buffer);
    int user_cluster = 0;
    if(cl.has_user((*ri).first))
      user_cluster = cl((*ri).first);
    //    if (u.size() > 0) cout << "Decachified " << buffer << ": size = " << u.size() << endl;
    for(User::iterator art = (*ri).second.begin();
        art != (*ri).second.end(); art++) {

      mod_count = min(all_mods.thing_counter[(*art).first].second, max_num-1);
      total_num[0]++;
      total_num[mod_count]++;
      total_num_cluster[user_cluster]++;

      if(u.has_key((*art).first)) {
        float guess = u[(*art).first];
        float actual = (*art).second;
        if (guess * actual > 0) 
	  if (actual > 0) {
            ++num_up_right[0];
            ++num_up_right[mod_count];
            ++num_up_right_cluster[user_cluster];
          }
          else {
            ++num_down_right[0];
            ++num_down_right_cluster[user_cluster];
            ++num_down_right[mod_count];
          }
        else if (guess * actual < 0) 
	  if (actual > 0) {
            ++num_up_wrong[0];
            ++num_up_wrong_cluster[user_cluster];
            ++num_up_wrong[mod_count];
          }
          else {
            ++num_down_wrong[0];
            ++num_down_wrong_cluster[user_cluster];
            ++num_down_wrong[mod_count];
          }
        else {
          no_guess[0]++;
          no_guess_cluster[user_cluster]++;
          no_guess[mod_count]++;
        }
      }
      else {
        no_guess[0]++;
        no_guess_cluster[user_cluster]++;
        no_guess[mod_count]++;
      }
    }
  }
  
  FILE *f = fopen("how_we_are_doing.out", "a");
  time_t t;
  fprintf(f,"Time: %ld\nEfficiency with mod number:\n", time(&t));
  printf("Time: %ld\nEfficiency with mod number:\n", time(&t));
  for(int i = 0; i < max_num; i++) {
    char text[100];
    if(i == 0)
      sprintf(text, "Total");
    else
      sprintf(text, "%5d", i);

    fprintf(f, "%s: %6d correct (%6d+/%6d-), %6d incorrect (%6d+/%6d-), and %6d unknown  (%5.2f%% correct, %5.2f%% accurate))\n",
            text, num_up_right[i] + num_down_right[i], num_up_right[i], num_down_right[i],
            num_up_wrong[i] + num_down_wrong[i], num_up_wrong[i], num_down_wrong[i],
            no_guess[i],
            100.*float(num_up_right[i]+num_down_right[i])/float(max(1, total_num[i]-no_guess[i])),
            100.*float(total_num[i]-no_guess[i])/float(total_num[i])
            );
    printf("%s: %6d correct (%6d+/%6d-), %6d incorrect (%6d+/%6d-), and %6d unknown  (%5.2f%% correct, %5.2f%% accurate))\n",
           text, num_up_right[i] + num_down_right[i], num_up_right[i], num_down_right[i],
           num_up_wrong[i] + num_down_wrong[i], num_up_wrong[i], num_down_wrong[i],
           no_guess[i],  
           100.*float(num_up_right[i]+num_down_right[i])/float(max(1, total_num[i]-no_guess[i])),
           100.*float(total_num[i]-no_guess[i])/float(total_num[i])
           );
  }
  fprintf(f,"Efficiency with cluster:\n");
  printf("Efficiency with cluster:\n");
  for(int i = 0; i < nclusters+1; i++) {
    char text[100];
    if(i == 0)
      sprintf(text, "Total");
    else
      sprintf(text, "%5d", i-1);

    fprintf(f, "%s: %6d correct (%6d+/%6d-), %6d incorrect (%6d+/%6d-), and %6d unknown  (%5.2f%% correct, %5.2f%% accurate)) (size: %5d)\n",
            text, num_up_right_cluster[i] + num_down_right_cluster[i], num_up_right_cluster[i], num_down_right_cluster[i],
            num_up_wrong_cluster[i] + num_down_wrong_cluster[i], num_up_wrong_cluster[i], num_down_wrong_cluster[i],
            no_guess_cluster[i],
            100.*float(num_up_right_cluster[i]+num_down_right_cluster[i])/float(max(1, total_num_cluster[i]-no_guess_cluster[i])),
            100.*float(total_num_cluster[i]-no_guess_cluster[i])/float(total_num_cluster[i]),
           (i > 0 && cl.size() > i-1)?cl.size(i-1):0
            );
    printf("%s: %6d correct (%6d+/%6d-), %6d incorrect (%6d+/%6d-), and %6d unknown  (%5.2f%% correct, %5.2f%% accurate)) (size: %5d)\n",
            text, num_up_right_cluster[i] + num_down_right_cluster[i], num_up_right_cluster[i], num_down_right_cluster[i],
            num_up_wrong_cluster[i] + num_down_wrong_cluster[i], num_up_wrong_cluster[i], num_down_wrong_cluster[i],
            no_guess_cluster[i],
            100.*float(num_up_right_cluster[i]+num_down_right_cluster[i])/float(max(1, total_num_cluster[i]-no_guess_cluster[i])),
           100.*float(total_num_cluster[i]-no_guess_cluster[i])/float(total_num_cluster[i]),
           (i > 0 && cl.size() > i-1)?cl.size(i-1):0
            );

  }
  fclose(f);

  delete[] num_up_right_cluster,
    num_up_wrong_cluster,
    num_down_right_cluster,
    num_down_wrong_cluster,
    no_guess_cluster,
    total_num_cluster;

}


void Recommender::cache_recommendations(set<int>& users, 
                                        set<int>& articles,
                                        bool startFresh)
{
  

  time_t _start_time = time(NULL);
  int terminator = -10;
  int num_total_recs  = 0;

  for(set<int>::iterator user = users.begin();
      user != users.end() && terminator--; user++) {
    char buffer[50];
    sprintf(buffer, "recommend_%d", (*user));

    User u;
    u.clear();
    if (!startFresh)
      u.decachify(buffer);

    time_t start_time = time(NULL);
    int n_attempts  = 0, n_attempts_max = 10;

    do {
      int rec_count = 0;
      for(set<int>::iterator art = articles.begin();
          art != articles.end(); art++) {
        if(!this->storeModdedArticles && 
           mods[(*user)].has_key(*art)) continue;
        float q = predict(*user, *art, n_attempts != 0 && art == articles.begin());
        int a = (*art);
        if(q != 0) {
          rec_count++;
          u.add(a, q);
        }
      }
      if(!rec_count && articles.size() > 100) {
        cout << " +++ Resorting to cluster behavior" << endl;
        double fudge0 = fudge;
        fudge = 1;
        for(set<int>::iterator art = articles.begin();
            art != articles.end(); art++) {
          if(mods[(*user)].has_key(*art)) continue;
          float q = predict(*user, *art);
          int a = (*art);
          if(q != 0) {
            rec_count++;
            u.add(a, q);
          }
        }
        fudge = fudge0;
      }

      num_total_recs += rec_count;
      
      if(rec_count > 20) {
        cout << " --> " << (*user) 
             << ": \x1b[32m\x1b[1mGenerated " << rec_count << " additional recommendations\x1b[0m"
             << endl;
        break;
      }
      else {
        cout << " --> \x1b[33m\x1b[1mFAILED TO GENERATE RECOMMENDATIONS (only " << rec_count << ")!!!\x1b[0m" << endl;
        cout << "     Available mods: " << mods[(*user)].size() << endl;
        char buffer[100];
        if(mods[(*user)].size() > 5) {
          cout << " --> \x1b[31m\x1b[1mFAILED TO GENERATE RECOMMENDATIONS (in the bad way)!!!\x1b[0m" << endl;
        }
      }
    } while(++n_attempts < n_attempts_max);

    if(u.size())
      u.memcachify(buffer);

    //      recs[*user].memcachify(buffer);

    cout << "\tFinished user " << (*user) << " (" 
         << difftime(time(NULL), start_time) << " sec, " 
         << articles.size() << " arts)" << endl;
  }
  cout << "Total recommendation time: " << difftime(time(NULL), _start_time)
       << " / " << users.size() << " users * " 
       << articles.size() << " articles \n\t --> " 
       << num_total_recs << " recs (@ " 
       << 1000./float(num_total_recs)*float(difftime(time(NULL), _start_time)) << " ms each)" << endl;

  //  fclose(toFile(fopen("user.data", "wb")));
}

Recommender::Recommender(char* fileName)  :
  mods(30), cl(10, mods)
{
  FILE *f = fopen(fileName, "rb"); 
  verbose = true;
  if(f) {
    //    fromFile(f); 
    //    fclose(f);
  }
  refresh();
}

Recommender::Recommender(int nclusters, int niterations, 
                         bool verbose, float fudge, int age, int mod_age,
                         bool storeModded) :
  mods(mod_age),
  cl(nclusters, mods)
{
  cout << "Calling init" << endl;
  cout << "Article age: " << age << endl;
  this->age = age;
  cout << "Fudge factor: " << fudge << endl;
  this->fudge = fudge;
  cout << "Verbose: " << verbose << endl;
  this->verbose = verbose;
  cout << "Number of Iterations " << niterations << endl;
  this->niterations = niterations;
  init(nclusters, niterations, verbose, fudge, age, storeModded);
}

void Recommender::init(int nclusters, int niterations, 
                       bool verbose, float fudge, int age, bool storeModded) 
{
  this->storeModdedArticles = storeModded;
  this->age = age;
  this->fudge = fudge;
  this->verbose = verbose;
  this->niterations = niterations;
  refresh(true);
}


/*FILE* Recommender::toFile(FILE* f) {
  fwrite(&nclusters, sizeof(int), 1, f);
  fwrite(&niterations, sizeof(int), 1, f);
  fwrite(&fudge, sizeof(double), 1, f);
  fwrite(&age, sizeof(age), 1, f);

  // save the clusters
  int _size = clusters.size();
  fwrite(&_size, sizeof(int), 1, f);
  for(vector<vector<int> >::iterator it = clusters.begin();
      it != clusters.end(); it++) {
    _size = (*it).size();
    fwrite(&_size, sizeof(int), 1, f);
    int i = 0;
    if(_size>0) {
      int* foo = new int[_size];
      for(i = 0; i < _size; i++) 
        foo[i] = (*it)[i];
      fwrite(foo, sizeof(int), _size, f);
      delete[] foo;
    }
  }

  // and the centroids
  _size = centroids.size();
  fwrite(&_size, sizeof(int), 1, f);
  for(vector<User>::iterator user = centroids.begin();
      user != centroids.end(); user++) {
    (*user).toFile(f);
  }
  
  // recs and clusters can save themselves
  //  recs.toFile(f);
  dbs_cluster.toFile(f);
  
  // and last save us the time of recomputing the sim_users table...
  _size = sim_users.size();
  fwrite(&_size, sizeof(int), 1, f);
  //  for(hash<int, vector<pair<int, float> > >::iterator u = sim_users.begin();
  for(map<int, vector<pair<int, float> > >::iterator u = sim_users.begin();
      u != sim_users.end(); u++) {
    _size = (*u).first;
    fwrite(&_size, sizeof(int), 1, f);
    _size = (*u).second.size();
    fwrite(&_size, sizeof(int), 1, f);
    for(vector<pair<int, float> >::iterator u2 = (*u).second.begin();
        u2 != (*u).second.end(); u2++) {
      _size = (*u2).first;
      fwrite(&_size, sizeof(int), 1, f);
      float foo = (*u2).second;
      fwrite(&foo, sizeof(float), 1, f);
    }
  }

  mods.toFile(f);
  return f;
}

void Recommender::fromFile(FILE* f) {
  fread(&nclusters, sizeof(int), 1, f);
  fread(&niterations, sizeof(int), 1, f);
  fread(&fudge, sizeof(double), 1, f);
  fread(&age, sizeof(age), 1, f);
  time_t mods_time;

  // wipe the existing clusters
  for(int j = 0; j < nclusters; j++) {
    if(j < clusters.size())  clusters[j].clear();
    if(j < centroids.size()) centroids[j].clear();
  }
  spread.clear();
  clusters.clear();
  centroids.clear();
  cluster_lookup.clear();

  int _size = 0, i = 0;
  fread(&_size, sizeof(int), 1, f);
  while(_size--) {
    int _size2;
    int readit = fread(&_size2, sizeof(int), 1, f);
    clusters.push_back(vector<int>());
    spread.push_back(0);
    if(_size2 > 0) {
      int* foo = new int[_size2];
      fread(foo, sizeof(int), _size2, f);
      for(int j = 0; j < _size2; j++) {
        clusters[i].push_back(foo[j]);
        cluster_lookup[foo[j]] = i;
      }
      delete[] foo;
    }
    cout << " --> Regenerated Cluster #" << i << ": with " 
         << clusters[i].size() << " users" << endl;
    i++;
  }

  cout << "Regenerating Clusters... (";
  fread(&_size, sizeof(int), 1, f);
  cout << _size << ")" << endl;
  i = 0;
  while(_size--) {
    User u;
    u.fromFile(f);
    cout << " --> Centroid " << i << " size: " << u.size() << endl;
    centroids.push_back(u);
    i++;
  }

  cout << "Regenerating Recommendations..." << endl;
  //  recs.fromFile(f);
  //  cout << " --> Recs size: " << recs.size() << endl;
  cout << "Regenerating Mods Approximation..." << endl;
  dbs_cluster.fromFile(f);
  cout << " --> Approx size: " << dbs_cluster.size() << endl;
  
  //  cout << "Regenerating user similarity table..." << endl;
 
  _size = 0;
  int _size2 = 0;
  i = 0;
  fread(&_size, sizeof(int), 1, f);
  cout << "Loading for " << _size << " users" << endl;
  while(_size--) {
    int user = 0;
    fread(&user, sizeof(int), 1, f);
    fread(&_size2, sizeof(int), 1, f);
    //    sim_users.add(user,  vector<pair<int, float> >());
    sim_users[user] =  vector<pair<int, float> >();
    while(_size2--) {
      pair<int, float> p;
      fread(&p.first, sizeof(int), 1, f);
      fread(&p.second, sizeof(float), 1, f);
      //sim_users[user].second.push_back(p);
      sim_users[user].push_back(p);
    }
  }
 
  mods.fromFile(f);

}

*/
