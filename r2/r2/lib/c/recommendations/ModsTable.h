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

#ifndef _MODSTABLE_H_
#define _MODSTABLE_H_
#include "SparseMatrix.h"
#include <time.h>
#include <libpq-fe.h>
#include <vector>
#include <set>
#include "User.h"

class RecTable : public hash<int, User> {
 protected:

 public:
  void clear() {
    for(iterator it = begin(); it != end(); it++) 
      (*it).second.clear();
    hash<int,User>::clear();
  }
  
  User& operator[](int user) {
    return (*(hash<int, User>*)this)[user].second;
  }

  float operator()(int u, int a) {
    return (*this)[u][a];
  }

  void operator()(int u, int a, float q) {
    if(!has_key(u)) 
      add(u, User());
    (*this)[u].add(a, q);
  }

  bool has(int u, int a) {
    return (has_key(u) && (*this)[u].has_key(a));
  }

  FILE* toFile(FILE * f) {
    int _size = size();
    fwrite(&_size, sizeof(int), 1, f);
    for(iterator it = begin(); it != end(); it++) {
      fwrite(&((*it).first), sizeof(int), 1, f);
      (*it).second.toFile(f);
    }
    return f;
  }

  void fromFile(FILE* f) {
    int user_id = 0;
    clear();
    int _size = 0;
    if(fread(&_size, sizeof(int), 1, f)) {
      while(_size--) {
        fread(&user_id, sizeof(int), 1, f);
        User u;
        u.fromFile(f);
        add(user_id, u);
      }
    }
  }

  friend ostream& operator<<(ostream & os, RecTable u) {
    for(RecTable::iterator it = u.begin(); it != u.end(); it++) {
      if(it != u.begin())
        os << ", ";
      os << (*it).first << ": " << (*it).second << endl;
    }
    return os;
  }
};




class ModsTable : public RecTable {
 protected:

  PGconn *pgdb;

  int age;
  float click_weight, submission_weight, mod_weight, save_weight;
  
  void load_mods_on_query(char * query);
  void load_on_where(char * where);

  double lastLoadTime;
  double firstModTime;

  RecTable *new_mods;


 public:

  RecTable the_big_players;

  hash<int, int> thing_counter;

  ModsTable(int age_in_days = 30, float mod_weight = 1, 
            float click_weight = 0,
            float submission_weight = 1, float save_weight = 0);
  
  
  float get(int user, int article) {
    return (*this)[user][article];
  }

  set<int> keys() {
    set<int> _keys;
    for(iterator it = begin();
        it != end(); it++)
      _keys.insert((*it).first);
    return _keys;
  }

  void reload(bool start_over);
  void load();
  void who_is_important();

  float user_distance(int user, map<int, float>* other);

  typedef pair<int, float>* art_iterator;
  art_iterator art_begin(int user);
  art_iterator art_end(int user);

 
  friend ostream& operator<<(ostream& os, ModsTable& mods);
  void load_dates(char * where);

  void toFile(FILE*);
  void fromFile(FILE*);

  RecTable &newMods(bool rload) {
    reload(rload);
    return *new_mods;
  }
};

#endif
