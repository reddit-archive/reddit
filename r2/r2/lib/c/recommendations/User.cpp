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

#include "User.h"
#include <math.h>
#include <set>
#include <algorithm>
#include "recommend_memcache.h"
#include <math.h>
#include <iostream>

float operator|(User& u1, User& u2) {
  return distance(&u1, &u2);
}
          

float norm(User* i1) {
  if(!i1 || i1->empty()) return 0;
  User::iterator i;
  float rval = 0;
  for(i = i1->begin(); i != i1->end(); i++) 
    rval += (*i).second * (*i).second;
  return sqrt(rval);
}

float dot(User* u1, User* u2) {
  if(!u1 || !u2 || u1->empty() || u2->empty()) return 0;
  User *i1 = u1;
  User *i2 = u2;
  if(u1->size() > u2->size()) {
    User * temp = i1;
    i1 = i2; i2 = temp;
  }
  float dist = 0;
  for(User::iterator i = i1->begin(); i != i1->end(); i++) 
      if(i2->has_key((*i).first)) {
        float part1 = (*i).second;
        float part2 = 0;
        if((*i2).has_key((*i).first))
          part2 = (*i2)[(*i).first];
        dist += part1 * part2;
      }
  return dist;
}


float dist(User* u1, User* u2, bool strict) {
  if(!u1 || !u2 || u1->empty() || u2->empty()) return 0;
  User *i1 = u1;
  User *i2 = u2;
  if(u1->size() > u2->size()) {
    User * temp = i1;
    i1 = i2; i2 = temp;
  }
  
  float denom1 = 0, denom2 = 0, dist = 0;
  if(strict) {
    set<int> seen_it;
    User::iterator i;
    for(i = i1->begin(); i != i1->end(); i++) 
      seen_it.insert((*i).first);
    for(i = i2->begin(); i != i2->end(); i++) 
      seen_it.insert((*i).first);
    for(set<int>::iterator art = seen_it.begin(); 
        art != seen_it.end(); art++)
      {
        float part1 = 0;
        if((*i1).has_key((*art)))
          part1 = (*i1)[(*art)];
        float part2 =0;
        if((*i2).has_key((*art)))
          part2 = (*i2)[(*art)];
        dist += part1 * part2;
        denom1 += part1 * part1;
        denom2 += part2 * part2;
      }
  }
  else {
    for(User::iterator i = i1->begin(); i != i1->end(); i++) 
      if(i2->has_key((*i).first)) {
        float part1 = (*i).second;
        float part2 = (*i2)[(*i).first];
        dist += part1 * part2;
        denom1 += part1 * part1;
        denom2 += part2 * part2;
      }
  }

  if(denom1*denom2 == 0) return 0;
  return dist/sqrt(denom1*denom2);
}


vector<pair<int, float> > User::sort() {
  vector<pair<int, float> > vec(*((vector<pair<int, float> >*)this));
  std::sort(vec.begin(), vec.end(), hash_sort_comp());
  return vec;
}



size_t entry_to_bytes(pair<int, float>& vals, char * dest, float norm = 1.) {
  int i = int_to_bytes(vals.first, dest);
  dest[i] = (char)(signed char)max(-127, min(127, int(vals.second/norm*128.)));
  int (size_t)(i+1);
}



pair<char*, size_t>  User::toBinary(bool rescale) {
  const int record_size = (sizeof(int) + 1);
  pair<float, float> m_m = min_max();

  char * record = new char[record_size*size() + 2 * sizeof(int)];
  char * rec_ptr = record;
  *(rec_ptr++) = char(record_size);
  if(m_m.first == 0 && m_m.second == 0) {
    rec_ptr += int_to_bytes(0, rec_ptr);
  }
  else {
    float scale = rescale ? max(-m_m.first, m_m.second) : 1.;
    vector<pair<int, float> > vec = sort();
    rec_ptr += int_to_bytes(vec.size(), rec_ptr);
    for(vector<pair<int, float> >::iterator it = vec.begin();
        it != vec.end(); it++) {
      entry_to_bytes((*it), rec_ptr, scale);
      rec_ptr += record_size;
    }
    vec.clear();
  }
  return pair<char*, size_t>(record, rec_ptr - record);
}


void User::fromBinary(char * record, float scale) {
  //  int record_size = (int)(record++);
  int num_records = bytes_to_int(++record);
  record += sizeof(int);
  for(int i = 0; i < num_records; i++) {
    int key = bytes_to_int(record);
    record += sizeof(int);
    float val = scale * float((record++)[0])/128.;
    if(val > 1) val -= 2;
    add(key, val);
  }
}


void User::toFile(FILE* os) {
  pair<char*, size_t> record = toBinary();
  fwrite(&(record.second), sizeof(size_t), 1, os);
  fwrite(record.first, 1, record.second, os);
  delete record.first;
}


void User::fromFile(FILE* is) {
  int num_values;
  clear();
  if(grab_int(is, num_values) && num_values)  {
    char *buffer = new char[num_values];
    fread(buffer, 1, num_values, is);
    fromBinary(buffer);
    delete buffer;
  }
}


void User::memcachify(char* name) {
  pair<char*, size_t> record = toBinary(true);
  pair<float, float> m_m = min_max();
  float x[2];
  x[0] = m_m.first;
  x[1] = m_m.second;
  cout << "\tStoring " << size() << " records and " << 
    record.second << " bytes  --> " << name << endl;
  mc.set(name, record.first, record.second);
  char name2[80];
  sprintf(name2, "%s_min_max", name);
  mc.set(name2, x, 2*sizeof(float));
  delete record.first;
  
}

void User::decachify(char* name) {
  char name2[80];
  sprintf(name2, "%s_min_max", name);
  float* foo3 = (float*)mc.get(name2);
  float min0 = -1;
  float max0 = 1;
  if(foo3) {
    min0 = foo3[0];
    max0 = foo3[1];
    char* foo2 = (char*)mc.get(name);
    if(foo2) {
      fromBinary(foo2, max(-min0, max0));
      delete foo2;
    }
    delete foo3;
  }
}

pair<float, float> User::min_max() {
  float min0 = 1;
  float max0 = -1;
  for(User::iterator it = begin(); it!= end(); it++) {
    min0 = min(min0, (*it).second);
    max0 = max(max0, (*it).second);
  }
  return pair<float, float>(min0, max0);
}
