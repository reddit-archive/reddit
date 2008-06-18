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

#ifndef __USER_H__
#define __USER_H__
#include <map>
#include <set>
#include <vector>
#include <iostream>
#include "Dictionary.h"

using namespace std;


inline int int_to_bytes(int val, char* dest) {
  int i;
  for(i = 0; i < sizeof(int); i++)
    dest[i] = (char)((val >> 8*i) & 0xFF);
  return i;
}

inline bool grab_int(FILE* f, int& val) {
  return (fread(&val, sizeof(int), 1, f) == 1);
}


inline int bytes_to_int(char * vals) {
  int dest = 0;
  for(int i = 0; i < sizeof(int); i++) {
    dest = (dest << 8) | (vals[sizeof(int) - i - 1] & 0xFF);
  }
  return dest;
}



struct hash_sort_comp : 
  public binary_function<int, int, bool> {
  bool operator()(pair<int, float> x, pair<int, float> y) { 
    return x.second > y.second;
  }
};


template<typename _key, typename _value>
class hash : public vector<pair<_key, _value> >{
 protected:
  map<_key, int> article_lookup;
  
  pair<_key, _value> blank;

 public:
  int size() { return vector<pair<_key, _value> >::size(); }

  void add(_key art_id, _value mod) {
    if(!has_key(art_id)) {
      int n = vector<pair<_key, _value> >::size();
      article_lookup[art_id] = n;
      push_back(pair<_key, _value>(art_id, mod));
    }
    else {
      (*(vector<pair<_key, _value> >*)this)[article_lookup[art_id]].second = mod;
    }
  }
  
  void clear() { 
    vector<pair<_key, _value> >::clear();
    article_lookup.clear();
  }

  pair<_key, _value>& operator[](_key art) {
    if(article_lookup.find(art) != article_lookup.end()) {
      return (*(vector<pair<_key, _value> >*)this)[article_lookup[art]];
    }
    return blank;
  }

  bool has_key(_key key) { return article_lookup.find(key) != article_lookup.end(); }

};


class User : public hash<int, float> {
 public:
  typedef vector<pair<int, float> >::iterator iterator;
  
  float& operator[](int art) {
    return (*((hash<int, float>*)(this)))[art].second;
  }
  // a distance metric short-hand
  friend float operator|(User& u1, User& u2);
  
  // the distance between two users
  friend float dist(User* u1, User* u2, bool strict = false);
  friend float dot(User* u1, User* u2);

  friend float norm(User*);

  void print() {
    for(iterator user_it = begin();
        user_it != end(); user_it++) 
      cout << (*user_it).first << ", " 
           << (*user_it).second << endl;
  }
  vector<pair<int, float> >  sort();
  
  pair<char*, size_t>  toBinary(bool rescale = false);
  void fromBinary(char*, float = 1.);

  void memcachify(char* name);
  void decachify(char* name);
  
  pair<float, float> min_max();
  void toFile(FILE* os);
  void fromFile(FILE* os);

  friend ostream & operator<<(ostream& os, User u) {
    os << "{";
    for(User::iterator it = u.begin(); it != u.end(); it++) {
      if(it != u.begin())
        os << ", ";
      os << (*it).first << ": " << (*it).second;
    }
    os << "}";
    return os;
  }
};



#endif

