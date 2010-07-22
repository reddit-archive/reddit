import json
import httplib
import urllib
import urlparse
import base64
import datetime

class ApiClient:
    """
    Basic client for an account.
    It needs an API url to be constructed.
    It has methods to manage and access the indexes of the 
    account. The objects returned by these methods implement
    the IndexClient class.
    """
    
    def __init__(self, api_url):
        self.__api_url = api_url.rstrip('/')
    
    def get_index(self, index_name):
        return IndexClient(self.__index_url(index_name))
    
    def create_index(self, index_name):
        index = self.get_index(index_name)
        index.create_index()
        return index
    
    def delete_index(self, index_name):
        self.get_index(index_name).delete_index()
    
    def list_indexes(self):
        _, indexes = _request('GET', self.__indexes_url())
        return [IndexClient(k, v) for k, v in indexes.iteritems()]
    
    """ Api urls """
    def __indexes_url(self):      return '%s/%s/indexes' % (self.__api_url, 'v1')
    def __index_url(self, name):  return '%s/%s' % (self.__indexes_url(), name)
    
class IndexClient:
    """
    Client for a specific index.
    It allows to inspect the status of the index. 
    It also provides methods for indexing and searching said index.
    """
    
    def __init__(self, index_url, metadata=None):
        self.__index_url = index_url
        self.__metadata = metadata

    def exists(self):
        """
        Returns whether an index for the name of this instance
        exists, if it doesn't it can be created by calling
        self.create_index() 
        """
        try:
            self.refresh_metadata()
            return True
        except HttpException, e:
            if e.status == 404:
                return False
            else:
                raise

    def has_started(self):
        """
        Returns whether this index is responsive. Newly created
        indexes can take a little while to get started. 
        If this method returns False most methods in this class
        will raise an HttpException with a status of 503.
        """
        return self.refresh_metadata()['started']
    
    def get_code(self):
        return self.get_metadata()['code']
    
    def get_creation_time(self):
        """
        Returns a datetime of when this index was created 
        """
        return _isoparse(self.get_metadata()['creation_time'])
    

    def create_index(self):
        """
        Creates this index. 
        If it already existed a IndexAlreadyExists exception is raised. 
        If the account has reached the limit a TooManyIndexes exception is raised
        """
        try:
            status, _ = _request('PUT', self.__index_url)
            if status == 204:
                raise IndexAlreadyExists('An index for the given name already exists')
        except HttpException, e:
            if e.status == 409:
                raise TooManyIndexes(e.msg)
            raise e
        
    def delete_index(self):
        _request('DELETE', self.__index_url)
    
    def add_document(self, docid, fields, variables=None):
        """
        Indexes a document for the given docid and fields.
        Arguments:
            docid: unique document identifier
            field: map with the document fields
            variables (optional): map integer -> float with values for variables that can
                                  later be used in scoring functions during searches. 
        """
        data = {'docid': docid, 'fields': fields}
        if variables is not None:
            data['variables'] = variables
        _request('PUT', self.__docs_url(), data=data)
        
    def delete_document(self, docid):
        """
        Deletes the given docid from the index if it existed. otherwise, does nothing.
        Arguments:
            docid: unique document identifier
        """
        _request('DELETE', self.__docs_url(), data={'docid': docid})
    
    def update_variables(self, docid, variables):
        """
        Updates the variables of the document for the given docid.
        Arguments:
            docid: unique document identifier
            variables: map integer -> float with values for variables that can
                       later be used in scoring functions during searches. 
        """
        _request('PUT', self.__variables_url(), data={'docid': docid, 'variables': variables})
        
    def promote(self, docid, query):
        """
        Makes the given docid the top result of the given query.
        Arguments:
            docid: unique document identifier
            query: the query for which to promote the document 
        """
        _request('PUT', self.__promote_url(), data={'docid': docid, 'query': query})

    def add_function(self, function_index, definition):
        try:
            _request('PUT', self.__function_url(function_index), data={'definition': definition})
        except HttpException, e:
            if e.status == 400:
                raise InvalidDefinition(e.msg)
    
    def delete_function(self, function_index):
        _request('DELETE', self.__function_url(function_index))
    
    def list_functions(self):
        _, functions = _request('GET', self.__functions_url())
        return functions 
    
    def search(self, query, start=None, len=None, scoring_function=None, snippet_fields=None, fetch_fields=None):
        params = { 'q': query }
        if start is not None: params['start'] = start
        if len is not None: params['len'] = len
        if scoring_function is not None: params['function'] = scoring_function
        if snippet_fields is not None: params['snippet'] = snippet_fields
        if fetch_fields is not None: params['fetch'] = fetch_fields
        try:
            _, result = _request('GET', self.__search_url(), params=params)
            return result
        except HttpException, e:
            if e.status == 400:
                raise InvalidQuery(e.msg)
            raise

    """ metadata management """
    def get_metadata(self):
        if self.__metadata is None:
            return self.refresh_metadata()
        return self.__metadata

    def refresh_metadata(self):
        _, self.__metadata = _request('GET', self.__index_url)
        return self.__metadata

    """ Index urls """
    def __docs_url(self):       return '%s/docs' % (self.__index_url)
    def __variables_url(self):  return '%s/docs/variables' % (self.__index_url)
    def __promote_url(self):    return '%s/promote' % (self.__index_url)
    def __search_url(self):     return '%s/search' % (self.__index_url)
    def __functions_url(self):  return '%s/functions' % (self.__index_url)
    def __function_url(self,n): return '%s/functions/%d' % (self.__index_url, n)

class InvalidResponseFromServer(Exception):
    pass
class TooManyIndexes(Exception):
    pass
class IndexAlreadyExists(Exception):
    pass
class InvalidQuery(Exception):
    pass
class InvalidDefinition(Exception):
    pass
class Unauthorized(Exception):
    pass

class HttpException(Exception):
    def __init__(self, status, msg):
        self.status = status
        self.msg = msg
        super(HttpException, self).__init__('HTTP %d: %s' % (status, msg))

__USER_AGENT = 'IndexTank.PythonClient.v1'

def _is_ok(status):
    return status / 100 == 2

def _request(method, url, params={}, data={}, headers={}):
    splits = urlparse.urlsplit(url)
    hostname = splits.hostname
    port = splits.port
    username = splits.username
    password = splits.password
    # drop the auth from the url
    netloc = splits.hostname + (':%s' % splits.port if splits.port else '')
    url = urlparse.urlunsplit((splits.scheme, netloc, splits.path, splits.query, splits.fragment))
    if method == 'GET':
        params = urllib.urlencode(params)
        if params:
            if '?' not in url:
                url += '?' + params
            else:
                url += '&' + params

    connection = httplib.HTTPConnection(hostname, port)
    if username or password:
        credentials = "%s:%s" % (username, password)
        base64_credentials = base64.encodestring(credentials)
        authorization = "Basic %s" % base64_credentials[:-1]
        headers['Authorization'] = authorization
    if data:
        body = json.dumps(data, ensure_ascii=True)
    else:
        body = ''
    
    connection.request(method, url, body, headers)
    
    response = connection.getresponse()
    response.body = response.read()
    if _is_ok(response.status):
        if response.body:
            try:
                response.body = json.loads(response.body)
            except ValueError, e:
                raise InvalidResponseFromServer('The JSON response could not be parsed: %s.\n%s' % (e, response.body))
            ret = response.status, response.body
        else:
            ret = response.status, None
    elif response.status == 401:
        raise Unauthorized('Authorization required. Use your private api_url.')
    else:
        raise HttpException(response.status, response.body) 
    connection.close()
    return ret

def _isoparse(s):
    try:
        return datetime.datetime(int(s[0:4]),int(s[5:7]),int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19]))
    except:
        return None
