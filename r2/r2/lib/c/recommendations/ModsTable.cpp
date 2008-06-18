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

#include "ModsTable.h"
#include "Database.h"
#include <math.h>

const char _modtable[] = "reddit_rel_vote_account_link";
const char _vote_select[] = "select thing1_id as u, thing2_id as a, case when name = '1' then 1 else -1 end as b from reddit_rel_vote_account_link where name != '0'";

  
void ModsTable::load_dates(char * where) {
  static char buffer[1000];
  
  sprintf(buffer, "select extract(epoch from date) from %s where %s order by date desc limit 1;", _modtable, where);
  cout << buffer << endl;
  PGresult *res = PQexec(pgdb, buffer);
  cout << "Query done" << endl;
  if (PQresultStatus(res) != PGRES_TUPLES_OK) {
    cerr << "Query Failed:" << endl 
         << buffer << endl 
         <<  PQerrorMessage(pgdb) << endl;
    PQclear(res);
    exit(0);
  }

  int nFields = PQnfields(res);
  if(nFields != 1) {
    cerr << "Query returned with other than one columns!  Check the query"
         << endl;
      PQclear(res);
    exit(0);
  }
  lastLoadTime = atof(PQgetvalue(res, 0, 0));
  time_t t = (time_t)lastLoadTime;
  cout << "Last load time: " << lastLoadTime << " --> " << ctime(&t) << endl;
  PQclear(res);

  sprintf(buffer, "select extract(epoch from date) from %s where %s order by date limit 1;", _modtable, where);
  cout << buffer << endl;
  res = PQexec(pgdb, buffer);
  cout << "Query done" << endl;
  if (PQresultStatus(res) != PGRES_TUPLES_OK) {
    cerr << "Query Failed:" << endl 
         << buffer << endl 
         <<  PQerrorMessage(pgdb) << endl;
    PQclear(res);
    exit(0);
  }
  
  nFields = PQnfields(res);
  if(nFields != 1) {
    cerr << "Query returned with other than one columns!  Check the query"
         << endl;
      PQclear(res);
    exit(0);
  }
  firstModTime = atof(PQgetvalue(res, 0, 0));
  t = (time_t)firstModTime;
  cout << "First Mod time: " << firstModTime << " --> " << ctime(&t) << endl;
    
  PQclear(res);

}

ModsTable::ModsTable(int age_in_days, 
                     float _mod_weight, 
                     float _click_weight,
                     float _submission_weight, 
                     float _save_weight) :
  age(age_in_days), mod_weight(_mod_weight), click_weight(_click_weight),
  submission_weight(_submission_weight), save_weight(_save_weight)
{
  pgdb = NULL;
  new_mods = NULL;
}

void ModsTable::toFile(FILE* f) {
  fwrite(&lastLoadTime, sizeof(double), 1, f);
  fwrite(&firstModTime, sizeof(double), 1, f);
  fwrite(&age, sizeof(int), 1, f);

  fwrite(&click_weight, sizeof(float), 1, f);
  fwrite(&submission_weight, sizeof(float), 1, f);
  fwrite(&mod_weight, sizeof(float), 1, f);
  fwrite(&save_weight, sizeof(float), 1, f);
}


void ModsTable::fromFile(FILE * f) {
  fread(&lastLoadTime, sizeof(double), 1, f);
  fread(&firstModTime, sizeof(double), 1, f);
  fread(&age, sizeof(int), 1, f);

  fread(&click_weight, sizeof(float), 1, f);
  fread(&submission_weight, sizeof(float), 1, f);
  fread(&mod_weight, sizeof(float), 1, f);
  fread(&save_weight, sizeof(float), 1, f);
  
  char where[1000];
  char buffer[1000];

  
  sprintf(where, "extract(epoch from date) >= %f and extract(epoch from date) <= %f", firstModTime, lastLoadTime);
  load_on_where(where);
}



void ModsTable::reload(bool start_over) 
{
  cout << "Building Mods table" << endl;
  if(start_over) {
    this->lastLoadTime = 0;
    this->firstModTime = 0;
    this->thing_counter.clear();
    this->the_big_players.clear();
    clear();
  }
  if(new_mods) delete new_mods;
  new_mods = new RecTable();
  load();
  if(start_over)
    who_is_important();
}

void ModsTable::load_mods_on_query(char * query) {
  // execute query
  cout << query << endl;
  PGresult *res = PQexec(pgdb, query);
  cout << "Query done" << endl;


  if (PQresultStatus(res) != PGRES_TUPLES_OK)
    {
      cerr << "Query Failed:" << endl 
           << query << endl 
           <<  PQerrorMessage(pgdb) << endl;
      PQclear(res);
      return;
    }
  
  /* first, print out the attribute names */
  int i, nFields = PQnfields(res);
  if(nFields != 3) {
    cerr << "Query returned with other than three columns!  Check the query"
         << endl;
      PQclear(res);
      return;
  }

  /* next, print out the rows */
  SparseMatrix dbs;
  for (i = 0; i < PQntuples(res); i++)
    {
      int u = atoi(PQgetvalue(res, i, 0));
      int a = atoi(PQgetvalue(res, i, 1));
      float val = atof(PQgetvalue(res, i, 2));
      (*this)(u, a, val);
      (*new_mods)(u, a, val);
      if(this->thing_counter.has_key(a))
	this->thing_counter.add(a, this->thing_counter[a].second + 1);
      else
	this->thing_counter.add(a, 1);
    }
  
  PQclear(res);
}


void ModsTable::who_is_important() {
  const char *preamble = "|\t";

  cout << "===========================================" << endl;
  cout << preamble << "Who matters?  Glad you asked...." << endl;
  RecTable::iterator u;
  float mean = 0;
  float meansquare = 0;
  for(u = begin(); u != end(); u++) {
    int foo = (*u).second.size();
    mean += foo;
    meansquare += foo * foo;
  }
  mean /= float(size());
  meansquare = sqrt(meansquare/float(size()) - mean*mean);
  cout << preamble << "Distribution of mods: mean " << mean << " and rms " << meansquare << endl;

  for(u = begin(); u != end(); u++) 
    {
      if((*u).second.size() > mean) {
        for(User::iterator a = (*u).second.begin(); a != (*u).second.end(); a++)
          this->the_big_players((*u).first, (*a).first, (*a).second);
      }
    }
  cout << preamble << "Total users: " << size() << endl;
  cout << preamble << "Important users: " << the_big_players.size() << endl;
  cout << "===========================================" << endl;
}


void ModsTable::load() {
  static char where[100];
  // set up the default date restriction for the query depending on
  // whether this is a load or a reload
  if(pgdb || (pgdb = globalDB->connect())) {
    // fixing here.  last load date has to be updated only
    if(lastLoadTime) {
      sprintf(where, "date > to_timestamp(%f)", lastLoadTime);
      load_on_where(where);
      sprintf(where, 
              "date > (select max(date) from %s) - interval \'%d days\'", 
	      _modtable, age);
    }
    else {
      sprintf(where, 
              "date > (select max(date) from %s) - interval \'%d days\'", 
	      _modtable, age);
      load_on_where(where);
    }
    load_dates(where);
	  
    // close connection
    PQfinish(pgdb);
    pgdb = NULL;

  }
}




void ModsTable::load_on_where(char * where) {
  static char buffer[1000];

  // connect to postgresql
  if(pgdb || (pgdb = globalDB->connect())) {

    time_t t = time(NULL);
    // generate the query for the mods, and execute it
    sprintf(buffer, "%s and %s", _vote_select, where);
    load_mods_on_query(buffer);
    
    cout << "Done with mods load.  (Total time: " 
         << difftime(time(NULL), t) << " s)" << endl;
    
  }
}

  
ostream& operator<<(ostream& os, ModsTable& mods) {
  for(ModsTable::iterator user = mods.begin();
      user != mods.end(); user++) {
    for(User::iterator art = (*user).second.begin();
        art != (*user).second.end(); art++) {
      os << "(" << (*user).first << ", " << (*art).first 
         << ") -> " << (*art).second << endl;
    }
  }
  return os;
}
