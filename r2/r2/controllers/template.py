# "The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
# 
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
# 
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.base import *

class TemplateController(BaseController):
    def view(self, url):
        """
        This is the last place which is tried during a request to try to find a 
        file to serve. It could be used for example to display a template::
        
            def view(self, url):
                return render_response(url)
        
        Or, if you're using Myghty and would like to catch the component not
        found error which will occur when the template doesn't exist; you
        can use the following version which will provide a 404 if the template
        doesn't exist::
        
            import myghty.exception
            
            def view(self, url):
                try:
                    return render_response('/'+url)
                except myghty.exception.ComponentNotFound:
                    return Response(code=404)
        
        The default is just to abort the request with a 404 File not found
        status message.
        """
        abort(404)
