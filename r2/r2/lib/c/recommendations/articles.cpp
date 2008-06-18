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

#include "articles.h"
#include "Database.h"

RecentArticles::RecentArticles() {
  latestArticle = 0;
}

char _link_table[] = "reddit_thing_link";

hash<int, double>& RecentArticles::operator()(int age, bool reload) {
    cout << "Reloading most recent articles" << endl;

    PGconn * pgdb = globalDB->connect();
    if(!pgdb || PQstatus(pgdb) != CONNECTION_OK) {
      cout << "Failed to connect to DB"  << PQerrorMessage(pgdb) << endl;
      return latest_articles;
    }

    char query[1000];
    if(reload || !latestArticle) {
      cout << "Nuking and reloading latest articles" << endl;
      latest_articles.clear();
      sprintf(query, "select thing_id, extract(epoch from date) from %s where date > (select max(date) from reddit_rel_vote_account_link) - interval \'%d days\'", _link_table, age);
    }
    else {
      sprintf(query, 
             "select thing_id, extract(epoch from date) from date > to_timestamp(%f)", 
              _link_table, latestArticle);
    }
    PGresult *res = PQexec(pgdb, query);
    cout << query << endl;
    cout << "Query done" << endl;
    if (PQresultStatus(res) != PGRES_TUPLES_OK)  {
      cerr << "Query Failed:" << endl 
           <<  PQerrorMessage(pgdb) << endl;
      PQclear(res);
      return latest_articles;
    }
    for (int i = 0; i < PQntuples(res); i++)
      latest_articles.add(atoi(PQgetvalue(res, i, 0)),
                          atof(PQgetvalue(res, i, 1)));
    
    PQclear(res); 
    
    sprintf(query, "select extract(epoch from max(date)) from %s", _link_table);
    res = PQexec(pgdb, query);
    cout << query << endl;
    cout << "Query done" << endl;

    if (PQresultStatus(res) != PGRES_TUPLES_OK)  {
      cerr << "Query Failed:" << endl 
           <<  PQerrorMessage(pgdb) << endl;
      PQclear(res);
      return latest_articles;
    }
    latestArticle = atof(PQgetvalue(res, 0, 0));
    PQclear(res);
    
    PQfinish(pgdb);
    
    cout << "article load done" << endl;
    return latest_articles;
}

