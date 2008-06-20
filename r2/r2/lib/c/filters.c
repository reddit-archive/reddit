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
#include <Python.h>
#include <stdio.h>
#include <string.h>


PyObject *unicode_arg(PyObject *args) {
  PyObject * com;
  if (!PyArg_ParseTuple(args, "O", &com))
    return NULL;
  if (!PyUnicode_Check(com)) {
    PyErr_SetObject(PyExc_TypeError, Py_None);
    return NULL;
  }
  return com;
}



static PyObject *
filters_uwebsafe(PyObject * self, PyObject *args) 
{
  PyObject * com;
  Py_UNICODE * command;
  Py_UNICODE *buffer;
  PyObject * res;
  int ic=0, ib=0;
  int len;
  Py_UNICODE c;
  if (!(com = unicode_arg(args))) return NULL;
  command = PyUnicode_AS_UNICODE(com);
  len = PyUnicode_GetSize(com);

  buffer = (Py_UNICODE*)malloc(6*len*sizeof(Py_UNICODE));
  for(ic = 0, ib = 0; ic < len; ic++, ib++) {
    c = command[ic];
    if (c == '&') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'a';
      buffer[ib++] = (Py_UNICODE)'m';
      buffer[ib++] = (Py_UNICODE)'p';
      buffer[ib]   = (Py_UNICODE)';';
    }
    else if(c == (Py_UNICODE)'<') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'l';
      buffer[ib++] = (Py_UNICODE)'t';
      buffer[ib]   = (Py_UNICODE)';';
    }
    else if(c == (Py_UNICODE)'>') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'g';
      buffer[ib++] = (Py_UNICODE)'t';
      buffer[ib]   = (Py_UNICODE)';';
    }
    else if(c == (Py_UNICODE)'"') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'q';
      buffer[ib++] = (Py_UNICODE)'u';
      buffer[ib++] = (Py_UNICODE)'o';
      buffer[ib++] = (Py_UNICODE)'t';
      buffer[ib]   = (Py_UNICODE)';';      
    }
    else {
      buffer[ib] = command[ic];
    }
  }
  res = PyUnicode_FromUnicode(buffer, ib);
  free(buffer);
  return res;

}

static PyObject *
filters_uwebsafe_json(PyObject * self, PyObject *args) 
{
  PyObject * com;
  Py_UNICODE * command;
  Py_UNICODE *buffer;
  PyObject * res;
  int ic=0, ib=0;
  int len;
  Py_UNICODE c;
  if (!(com = unicode_arg(args))) return NULL;
  command = PyUnicode_AS_UNICODE(com);
  len = PyUnicode_GetSize(com);

  buffer = (Py_UNICODE*)malloc(5*len*sizeof(Py_UNICODE));
  for(ic = 0, ib = 0; ic < len; ic++, ib++) {
    c = command[ic];
    if (c == '&') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'a';
      buffer[ib++] = (Py_UNICODE)'m';
      buffer[ib++] = (Py_UNICODE)'p';
      buffer[ib]   = (Py_UNICODE)';';
    }
    else if(c == (Py_UNICODE)'<') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'l';
      buffer[ib++] = (Py_UNICODE)'t';
      buffer[ib]   = (Py_UNICODE)';';
    }
    else if(c == (Py_UNICODE)'>') {
      buffer[ib++] = (Py_UNICODE)'&';
      buffer[ib++] = (Py_UNICODE)'g';
      buffer[ib++] = (Py_UNICODE)'t';
      buffer[ib]   = (Py_UNICODE)';';
    }
    else {
      buffer[ib] = command[ic];
    }
  }
  res = PyUnicode_FromUnicode(buffer, ib);
  free(buffer);
  return res;

}


static PyObject *
filters_websafe(PyObject * self, PyObject *args) 
{
  const char * command;
  char *buffer;
  PyObject * res;
  int ic=0, ib=0;
  int len;
  char c;
  if (!PyArg_ParseTuple(args, "s", &command))
    return NULL;
  len = strlen(command);
  buffer = (char*)malloc(5*len);
  for(ic = 0, ib = 0; ic <= len; ic++, ib++) {
    c = command[ic];
    if (c == '&') {
      buffer[ib++] = '&';
      buffer[ib++] = 'a';
      buffer[ib++] = 'm';
      buffer[ib++] = 'p';
      buffer[ib]   = ';';
    }
    else if(c == '<') {
      buffer[ib++] = '&';
      buffer[ib++] = 'l';
      buffer[ib++] = 't';
      buffer[ib]   = ';';
    }
    else if(c == '>') {
      buffer[ib++] = '&';
      buffer[ib++] = 'g';
      buffer[ib++] = 't';
      buffer[ib]   = ';';
    }
    else if(c == '"') {
      buffer[ib++] = '&';
      buffer[ib++] = 'q';
      buffer[ib++] = 'u';
      buffer[ib++] = 'o';
      buffer[ib++] = 't';
      buffer[ib]   = ';';      
    }
    else {
      buffer[ib] = command[ic];
    }
  }
  res =  Py_BuildValue("s", buffer);
  free(buffer);
  return res;
}

void print_unicode(Py_UNICODE *c, int len) {
  int i;
  for(i = 0; i < len; i++) {
    printf("%d", (int)c[i]);
    if(i + 1 != len) printf(":");
  }
  printf("\n");
}

const char *MD_START = "<div class=\"md\">";
const char *MD_END = "</div>";
const Py_UNICODE *MD_START_U;
const Py_UNICODE *MD_END_U;
int MD_START_LEN = 0;
int MD_END_LEN = 0;



int whitespace(char c) {
  return (c == '\n' || c == '\r' || c == '\t' || c == ' ');
}


static PyObject *
filters_uspace_compress(PyObject * self, PyObject *args) {
  PyObject * com;
  PyObject * res;
  Py_ssize_t len;
  Py_UNICODE *command;
  Py_UNICODE *buffer;
  Py_UNICODE c;
  int ic, ib;
  int gobble = 1;
  com = unicode_arg(args);
  if(!com) {
    return NULL;
  }
  command = PyUnicode_AS_UNICODE(com);
  len = PyUnicode_GetSize(com);
  buffer = (Py_UNICODE*)malloc(len * sizeof(Py_UNICODE));

  for(ic = 0, ib = 0; ic <= len; ic++) {
    c = command[ic];
    if(gobble) {
      if(Py_UNICODE_ISSPACE(c)) {
        while(Py_UNICODE_ISSPACE(command[++ic]));
        c = command[ic];
        if(c != (Py_UNICODE)('<')) {
          buffer[ib++] = (Py_UNICODE)(' ');
        }
      }
      if(c == (Py_UNICODE)('>')) {
        buffer[ib++] = c;
        while(Py_UNICODE_ISSPACE(command[++ic]));
        c = command[ic];
      }
      if (len - ic >= MD_START_LEN &&
          memcmp(&command[ic], MD_START_U, 
                 sizeof(Py_UNICODE)*MD_START_LEN) == 0) {
        gobble = 0;
      }
    }
    else {
      if (len - ic > MD_END_LEN &&
          memcmp(&command[ic], MD_END_U, 
                 sizeof(Py_UNICODE)*MD_END_LEN) == 0) {
        gobble = 1;
      }
    }
    if(c) {
      buffer[ib++] = c;
    }
  }  

  res = PyUnicode_FromUnicode(buffer, ib);
  free(buffer);
  return res;
}


static PyObject *
filters_space_compress(PyObject * self, PyObject *args) 
{
  PyObject * res;

  const char * command;
  int len, ic, ib;
  char c;
  char * buffer;
  int gobble = 1;
  if (!PyArg_ParseTuple(args, "s", &command))
    return NULL;

  len = strlen(command);
  buffer = (char*)malloc(len);

  for(ic = 0, ib = 0; ic <= len; ic++) {
    c = command[ic];
    if(gobble) {
      if(c == '>') {
        buffer[ib++] = c;
        while(whitespace(command[++ic]));
        c = command[ic];
      }
      else if(whitespace(c)) {
        while(whitespace(command[++ic]));
        c = command[ic];
        if(c != '<') {
          buffer[ib++] = ' ';
        }
      }
      if (len - ic >= MD_START_LEN &&
               strncmp(&command[ic], MD_START, MD_START_LEN) == 0) {
        gobble = 0;
      }
    }
    else {
      if (len - ic > MD_END_LEN &&
          strncmp(&command[ic], MD_END, MD_END_LEN) == 0) {
        gobble = 1;
      }
    }
    buffer[ib++] = c;
  }  

  res =  Py_BuildValue("s", buffer);
  free(buffer);
  return res;
}

static PyMethodDef FilterMethods[] = {
  {"websafe",  filters_websafe, METH_VARARGS,
   "make string web safe."},
  {"uwebsafe",  filters_uwebsafe, METH_VARARGS,
   "make string web safe."},
  {"uwebsafe_json",  filters_uwebsafe_json, METH_VARARGS,
   "make string web safe, no &quot;."},
  {"space_compress",  filters_space_compress, METH_VARARGS,
   "returns meep"},
  {"uspace_compress",  filters_uspace_compress, METH_VARARGS,
   "returns meep"},
  {NULL, NULL, 0, NULL}        /* Sentinel */
};

Py_UNICODE *to_unicode(const char *c, int len) {
  Py_UNICODE *x = (Py_UNICODE *)malloc((len+1) * sizeof(Py_UNICODE));
  int i;
  for(i = 0; i < len; i++) {
    x[i] = (Py_UNICODE)c[i];
  }
  x[len] = (Py_UNICODE)(0);
  return x;
}


PyMODINIT_FUNC
initCfilters(void)
{
  MD_START_LEN = strlen(MD_START);
  MD_START_U = to_unicode(MD_START, MD_START_LEN);
  MD_END_LEN = strlen(MD_END);
  MD_END_U = to_unicode(MD_END, MD_END_LEN);

  (void) Py_InitModule("Cfilters", FilterMethods);
}

