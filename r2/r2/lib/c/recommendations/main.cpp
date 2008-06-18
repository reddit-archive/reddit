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

#include <iostream>
#include <fstream>
//#include <map>
using namespace std;
#include "SparseMatrix.h"
#include "ModsTable.h"
#include "articles.h"
#include "recommend_memcache.h"
#include "recommender_py.h"
//#include "libc.h"
#include <unistd.h>
#include "Dictionary.h"
#include "Database.h"
//#include <openssl/md5.h>

void lower(char * str) {
  for(int i = 0; i < strlen(str); i++)
    str[i] = tolower(str[i]);
}

void usage() {
  cout << "recommender: usage:" << endl
       << "\t? - This message" << endl
       << "\tf file_name" << endl
       << "\t    load all recs and previous compusations from file_name" << endl
       << "\tR - Restart recommender, recomputing clusters" << endl
       << "\tq - Turn off verbose mode" << endl
       << "\ta age" << endl
       << "\t    compute the recs for the last \"age\" days" << endl
       << "\tm age" << endl
       << "\t    use mods from the last age days to compute the recommendations."
       << endl << "\t    (default 30)" << endl
       << "\tu time_in_seconds" << endl
       << "\t    regenerate after time_in_seconds (default:60)" << endl
       << "\tr time_in_seconds" << endl
       << "\t    reinit clustering engine every time_in_seconds.  "
       << endl << "\t    (default: 1 day)" << endl;
}

int main (int argc, char * const argv[]) {
   Dictionary lookup;
   RecommenderEngine recommender;
   char ip[100];
   char port[100];

   char db_host[100];
   char db_name[100];
   char db_user[100];
   char db_password[100];

   int age = 0;
   int mod_age = 0; 


   char c;
   bool fromFile = false;
   bool restart = false;
   bool verbose = true;
   char *fileName = "user.data";
   
   
   int update_time = 60;
   int refresh_time = 86400;

   int ngroups = 40;
   bool enabled = true;
   char *configFileName = NULL;

   bool show_modded = true;

   while (enabled and (c = getopt (argc, argv, "?Rf:r:qa:m:u:g:F:")) != -1) {
     switch (c) {
     case 'F':
       configFileName = new char[strlen(optarg)];
       strcpy(configFileName, optarg);
       enabled = false;
       break;
     case 'f':
       fromFile = true;
       fileName = optarg;
       cout << "Loading from file: \"" << fileName << "\"" << endl;
       break;
     case 'R':
       restart = true;
       cout << "Forcing reinitializaiont of clusters" << endl;
       break;
     case 'q':
       verbose = false;
       cout << "Verbose deactivated" << endl;
       break;
     case 'a':
       age = atoi(optarg);
       cout << "Age of recommended articles: " << age << endl;
       break;
     case 'm':
       mod_age = atoi(optarg);
       cout << "Age of mod table to use: " << mod_age << endl;
       break;
     case 'g':
       ngroups = atoi(optarg);
       break;
     case 'u':
       update_time = atoi(optarg);
       cout << "Update every: " << update_time << " sec" << endl;
       break;
     case 'r':
       refresh_time = atoi(optarg);
       cout << "Refresh every: " << refresh_time << " sec" << endl;
       break;
     case '?':
       if (isprint (optopt))
         fprintf (stderr, "Unknown option `-%c'.\n", optopt);
       else
         fprintf (stderr,
                  "Unknown option character `\\x%x'.\n",
                  optopt);
       usage();
       return 1;
     default:
       abort ();
     }

     // if we have hit a configuration file, skip all of the above stuff and load
     // straight from the file
     if(configFileName) {
       ifstream ifile(configFileName);
       char buffer[100];
       while(ifile.getline(buffer, 100)) {
         char str[100];
         char val[100];
         if(sscanf(buffer, "%s %s", str, val) == 2) {
           lower(str);
           char *foo3 = new char[strlen(str)+1];
           strcpy(foo3, str);
           lookup[foo3] = new char[strlen(val)+1];
           strcpy(lookup[foo3], val);
         }
       }
       strcpy(ip, lookup["ip"]);


       strcpy(port, lookup["port"]);
       ngroups = atoi(lookup["ngroups"]);
       age = atoi(lookup["age"]);
       mod_age = atoi(lookup["mods"]);

       update_time = atoi(lookup["update_time"]);
       refresh_time = atoi(lookup["refresh_time"]);
       restart = (atoi(lookup["restart"]) == 0);
       verbose = (atoi(lookup["verbose"]) == 0);

       strcpy(db_user, lookup["db_user"]);
       strcpy(db_name, lookup["db_name"]);
       strcpy(db_host, lookup["db_host"]);
       strcpy(db_password, lookup["db_password"]);

       globalDB = new Database(db_name, db_host, db_user, db_password);

       cout << "Memcached: " << ip << ":" << port << endl;
       cout << "Database: " << db_name << " on " << db_host << " (" << db_user << ", " << db_password << ")" << endl;
       if(restart)
         cout << "Forcing reinitialization of clusters" << endl;
       if(!verbose)
         cout << "Verbose deactivated" << endl;
       cout << "Age of recommended articles: " << age << endl;
       cout << "Age of mod table to use: " << mod_age << endl;
       cout << "Number of groups: " << ngroups << endl;
       cout << "Update every: " << update_time << " sec" << endl;
       cout << "Refresh every: " << refresh_time << " sec" << endl;
       if(show_modded)
         cout << "storing Modded articles: " << endl;

     }
 
   }

   if(configFileName == NULL) {
     printf("Please specify a parameters file with \"-F\"\n");
     return -1;
   }

   recommender.add_mc_server(ip, port);


   if(fromFile) {
     recommender.load(fileName);
     if(restart) recommender.refresh(true);
   }
   else {
     recommender.init(verbose, age, mod_age, ngroups, 10, 0,show_modded);
   }
     
   
   long day = time(NULL)/refresh_time;
   while(1) {
     sleep(update_time);
     if (time(NULL)/refresh_time > day) {
       day = time(NULL)/refresh_time;
       recommender.refresh(true);
     }
     else
       recommender.refresh(false);
       }

  return 0;
}
