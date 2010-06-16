import urllib
import json 

#BASE_URL = 'http://api.indextank.com/api/v0'
BASE_URL = 'http://api.reddit.indextank.com/api/v0'
#BASE_URL = 'http://api.it-test.flaptor.com/api/v0'


class IndexTank:
    api_key=None
    def_index_code=None
    
    def __init__(self, api_key, index_code=None):
        self.api_key = api_key
        self.def_index_code = index_code
    
    def __api_call(self, method, index_code=None, params={}):
        base_params = { 
            'api_key': self.api_key,
            'index_code': index_code or self.def_index_code,
        }
        base_params.update(params)
        params = urllib.urlencode(base_params)
        url = "%s/%s"%(BASE_URL,method)
        res = urllib.urlopen(url,params)
        data = res.read()
        if 200 != res.getcode():
            return False, 'HttpResponse code %d\nResponse content is:\n%s' % (res.getcode(), data)
        try:
            result = json.loads(data)
        except ValueError,e:
            return False, 'Error decoding json response.\nResponse content is:\n%s' % (data)
        ok = result.get('status') == 'OK'
        return ok, result
    
    def create_index(self, index_name=''):
        data = { 'index_name': index_name}
        return self.__api_call("admin/create",params = data)
    
    def delete_index(self, index_code=None):
        return self.__api_call("admin/delete",index_code=index_code)
    
    def list_indexes(self):
        return self.__api_call("admin/list")
    
    def add(self, doc_id, content, boosts=None, index_code=None):
        '''
            doc_id: unique document identifier
            content: map with the document fields
            boosts (optional): map integer -> float with values for available boosts
            index_code (optional): index code if not specified in construction 
        '''
        if boosts:
            dumped_boosts = json.dumps(boosts)
            data = { 'document': json.dumps(content), 'document_id': doc_id, 'boosts': dumped_boosts}
        else:
            data = { 'document': json.dumps(content), 'document_id': doc_id}
        
        return self.__api_call("index/add",index_code=index_code,params=data)
    
    def boost(self, doc_id, timestamp=None, boosts=None, index_code=None):
        data = {'document_id': doc_id}
        if timestamp:
            data.update({ 'timestamp': str(timestamp)})
        if boosts:
            data.update({ 'boosts': json.dumps(boosts)})
        return self.__api_call("index/boost",index_code=index_code,params=data)

    def promote(self, doc_id, query):
        data = { 'document_id' : doc_id, 'query' : query }
        return self.__api_call("index/promote", index_code=index_code, params=data)

    def add_function(self, function_index, definition, index_code=None):
        data = { 'function_id': function_index, 'definition': definition }
        return self.__api_call("index/add_function", index_code=index_code, params=data)
    
    def del_function(self, function_index, index_code=None):
        data = { 'function_id': function_index }
        return self.__api_call("index/remove_function", index_code=index_code, params=data)
    
    def list_functions(self, index_code=None):
        return self.__api_call("index/list_functions", index_code=index_code, params={})
    
    def update(self, doc_id, content, index_code=None):
        data = { 'document': json.dumps(content), 'document_id':doc_id}
        return self.__api_call("index/update", index_code=index_code, params=data)
    
    def delete(self, doc_id, index_code=None):
        data = { 'document_id':doc_id}
        return self.__api_call("index/delete",index_code=index_code,params=data)
   
 
    def search(self, query, index_code=None, start=0, len=10, relevance_function=None, snippet_fields=None, fetch_fields=None):
        data = { 'query':query, 'start':start, 'len':len, 'snippet_fields':snippet_fields, 'fetch_fields':fetch_fields,}
        if relevance_function is not None:
            data['relevance_function'] = relevance_function
        return self.__api_call("search/query",index_code=index_code,params=data)

    def complete(self, query, index_code=None):
        data = { 'query':query }
        return self.__api_call("search/complete", index_code=index_code, params=data)
       
    def index_stats(self, index_code=None):
        return self.__api_call("index/stats",index_code=index_code)
    
    def search_stats(self, index_code=None):
        return self.__api_call("search/stats",index_code=index_code)

