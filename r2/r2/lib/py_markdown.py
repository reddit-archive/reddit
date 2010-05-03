from contrib.markdown import markdown
import re

r_url = re.compile('(?<![\(\[])(http://[^\s\'\"\]\)]+)')
jscript_url = re.compile('<a href="(?!http|ftp|mailto|/).*</a>', re.I | re.S)
img = re.compile('<img.*?>', re.I | re.S)
href_re = re.compile('<a href="([^"]+)"', re.I)
code_re = re.compile('<code>([^<]+)</code>')
a_re    = re.compile('>([^<]+)</a>')
fix_url = re.compile('&lt;(http://[^\s\'\"\]\)]+)&gt;')

def code_handler(m):
    l = m.group(1)
    return '<code>%s</code>' % l.replace('&amp;','&')

#unescape double escaping in links
def inner_a_handler(m):
    l = m.group(1)
    return '>%s</a>' % l.replace('&amp;','&')

def py_markdown(text, nofollow=False, target=None):
    # increase escaping of &, < and > once
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    #wrap urls in "<>" so that markdown will handle them as urls
    text = r_url.sub(r'<\1>', text)

    text = markdown(text)

    text = img.sub('', text) #remove images
    # remove the "&" escaping in urls
    text = code_re.sub(code_handler, text)
    text = a_re.sub(inner_a_handler, text)

    #remove images
    text = img.sub('', text)

    #wipe malicious javascript
    text = jscript_url.sub('', text)

    # remove the "&" escaping in urls
    def href_handler(m):
        url = m.group(1).replace('&amp;', '&')
        link = '<a href="%s"' % url

        if target:
            link += ' target="%s"' % target

        if nofollow:
            link += ' rel="nofollow"'

        return link

    text = href_re.sub(href_handler, text)
    text = code_re.sub(code_handler, text)
    text = a_re.sub(inner_a_handler, text)
    text = fix_url.sub(r'\1', text)

    return text
