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

#ifndef _SPARSEMATRIX_H_
#define _SPARSEMATRIX_H_
#include <map>
#include <iostream>

using namespace std;

typedef map<int, float> SparseMatrixRow;
  

class SparseMatrix {
 public:
  
  map<int, SparseMatrixRow> data;
  typedef map<int, SparseMatrixRow>::iterator iterator;
 public:
  float &operator()(const int s1, const int s2) {
    return data[s1][s2];
  }
  
  iterator begin() { return data.begin(); }
  iterator end() { return data.end(); }

  SparseMatrixRow& operator[](int i) { return data[i]; }
  
  int size() {return data.size(); }
  
  bool has_key(int key) { return data.count(key) != 0; }
  bool empty() { return data.empty(); }
  
  // Function to wipe the matrix and all of its rows
  // (hopefully to prevent memory leaks)
  void clear() {
    for(SparseMatrix::iterator cur = data.begin(); 
        cur != data.end(); cur ++)  {
      (*cur).second.clear();
    }
    data.clear();
  }

  friend ostream& operator<<(ostream& os, SparseMatrix& sm) {
    for(SparseMatrix::iterator cur = sm.data.begin(); 
        cur != sm.data.end(); cur ++)  {
      for(SparseMatrixRow::iterator cur2 = (*cur).second.begin(); 
          cur2 != (*cur).second.end(); cur2++) {
        os << (*cur).first << ", " << (*cur2).first << ", " << 
          (*cur2).second << endl;
      }
    }
    return os;
  }
};

#endif
