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

#include "Database.h"
#include <string.h>
#include <iostream>
#include <fstream>

using namespace std;

#define strinit(A, B) A = new char[strlen(B)+1]; strcpy(A, B)

Database::Database(char* _name, char* _ip, char *_user, char* _password)
{
  strinit(name, _name);
  strinit(ip, _ip);
  strinit(user, _user);
  strinit(password, _password);
  connect();
}



PGconn* Database::connect() {
  if(!connection || PQstatus(connection) != CONNECTION_OK) {

    cout << "Connecting to Db...." << endl;
    char buffer[200];
    sprintf(buffer, "user=\'%s\' password=\'%s\' dbname=\'%s\' host=\'%s\'", user, password, name, ip);
    cout << buffer << endl;
    PGconn *pgdb = PQconnectdb(buffer);
    
    if(!pgdb || PQstatus(pgdb) != CONNECTION_OK) {
      cout << "Failed to connect to DB"  << PQerrorMessage(pgdb) << endl;
      return NULL;
    }
    else {
      cout << "Connected: " << endl 
           << "  DB:\t" << PQdb(pgdb) << endl
           << "  User:\t" << PQuser(pgdb) << endl;
    }
    connection = pgdb;
    return pgdb;
  }
  else
    return connection;
}

Database* globalDB = NULL;

