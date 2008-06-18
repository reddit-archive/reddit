#!/usr/bin/python
import re, md5, sys, string

"""markdown.py: A Markdown-styled-text to HTML converter in Python.

Usage:
  ./markdown.py textfile.markdown
 
Calling:
  import markdown
  somehtml = markdown.markdown(sometext)
"""

__version__ = '1.0.1-2' # port of 1.0.1
__license__ = "GNU GPL 2"
__author__ = [
  'John Gruber <http://daringfireball.net/>',
  'Tollef Fog Heen <tfheen@err.no>', 
  'Aaron Swartz <me@aaronsw.com>'
]

def htmlquote(text):
    """Encodes `text` for raw use in HTML."""
    text = text.replace("&", "&amp;") # Must be done first!
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("'", "&#39;")
    text = text.replace('"', "&quot;")
    return text

def semirandom(seed):
    x = 0
    for c in md5.new(seed).digest(): x += ord(c)
    return x / (255*16.)

class _Markdown:
    emptyelt = " />"
    tabwidth = 4

    escapechars = '\\`*_{}[]()>#+-.!'
    escapetable = {}
    for char in escapechars:
        escapetable[char] = md5.new(char).hexdigest()
    
    r_multiline = re.compile("\n{2,}")
    r_stripspace = re.compile(r"^[ \t]+$", re.MULTILINE)
    def parse(self, text):
        self.urls = {}
        self.titles = {}
        self.html_blocks = {}
        self.list_level = 0
        
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        text += "\n\n"
        text = self._Detab(text)
        text = self.r_stripspace.sub("", text)
        text = self._HashHTMLBlocks(text)
        text = self._StripLinkDefinitions(text)
        text = self._RunBlockGamut(text)
        text = self._UnescapeSpecialChars(text)
        return text
    
    r_StripLinkDefinitions = re.compile(r"""
    ^[ ]{0,%d}\[(.+)\]:  # id = $1
      [ \t]*\n?[ \t]*
    <?(\S+?)>?           # url = $2
      [ \t]*\n?[ \t]*
    (?:
      (?<=\s)            # lookbehind for whitespace
      [\"\(]             # " is backlashed so it colorizes our code right
      (.+?)              # title = $3
      [\"\)]
      [ \t]*
    )?                   # title is optional
    (?:\n+|\Z)
    """ % (tabwidth-1), re.MULTILINE|re.VERBOSE)
    def _StripLinkDefinitions(self, text):
        def replacefunc(matchobj):
            (t1, t2, t3) = matchobj.groups()
            #@@ case sensitivity?
            self.urls[t1.lower()] = self._EncodeAmpsAndAngles(t2)
            if t3 is not None:
                self.titles[t1.lower()] = t3.replace('"', '&quot;')
            return ""

        text = self.r_StripLinkDefinitions.sub(replacefunc, text)
        return text

    blocktagsb = r"p|div|h[1-6]|blockquote|pre|table|dl|ol|ul|script|math"
    blocktagsa = blocktagsb + "|ins|del"
    
    r_HashHTMLBlocks1 = re.compile(r"""
    (            # save in $1
    ^            # start of line  (with /m)
    <(%s)        # start tag = $2
    \b           # word break
    (.*\n)*?     # any number of lines, minimally matching
    </\2>        # the matching end tag
    [ \t]*       # trailing spaces/tabs
    (?=\n+|$)    # followed by a newline or end of document
    )
    """ % blocktagsa, re.MULTILINE | re.VERBOSE)

    r_HashHTMLBlocks2 = re.compile(r"""
    (            # save in $1
    ^            # start of line  (with /m)
    <(%s)        # start tag = $2
    \b           # word break
    (.*\n)*?     # any number of lines, minimally matching
    .*</\2>      # the matching end tag
    [ \t]*       # trailing spaces/tabs
    (?=\n+|\Z)   # followed by a newline or end of document
    )
    """ % blocktagsb, re.MULTILINE | re.VERBOSE)

    r_HashHR = re.compile(r"""
    (?:
    (?<=\n\n)    # Starting after a blank line
    |            # or
    \A\n?        # the beginning of the doc
    )
    (            # save in $1
    [ ]{0,%d}
    <(hr)        # start tag = $2
    \b           # word break
    ([^<>])*?    # 
    /?>          # the matching end tag
    [ \t]*
    (?=\n{2,}|\Z)# followed by a blank line or end of document
    )
    """ % (tabwidth-1), re.VERBOSE)
    r_HashComment = re.compile(r"""
    (?:
    (?<=\n\n)    # Starting after a blank line
    |            # or
    \A\n?        # the beginning of the doc
    )
    (            # save in $1
    [ ]{0,%d}
    (?: 
      <!
      (--.*?--\s*)+
      >
    )
    [ \t]*
    (?=\n{2,}|\Z)# followed by a blank line or end of document
    )
    """ % (tabwidth-1), re.VERBOSE)

    def _HashHTMLBlocks(self, text):
        def handler(m):
            key = m.group(1)
            try:
                key = key.encode('utf8')
            except UnicodeDecodeError:
                key = ''.join(k for k in key if ord(k) < 128)
            key = md5.new(key).hexdigest()
            self.html_blocks[key] = m.group(1)
            return "\n\n%s\n\n" % key

        text = self.r_HashHTMLBlocks1.sub(handler, text)
        text = self.r_HashHTMLBlocks2.sub(handler, text)
        oldtext = text
        text = self.r_HashHR.sub(handler, text)
        text = self.r_HashComment.sub(handler, text)
        return text

    #@@@ wrong!
    r_hr1 = re.compile(r'^[ ]{0,2}([ ]?\*[ ]?){3,}[ \t]*$', re.M)
    r_hr2 = re.compile(r'^[ ]{0,2}([ ]?-[ ]?){3,}[ \t]*$', re.M)
    r_hr3 = re.compile(r'^[ ]{0,2}([ ]?_[ ]?){3,}[ \t]*$', re.M)
	
    def _RunBlockGamut(self, text):
        text = self._DoHeaders(text)
        for x in [self.r_hr1, self.r_hr2, self.r_hr3]:
            text = x.sub("\n<hr%s\n" % self.emptyelt, text);
        text = self._DoLists(text)
        text = self._DoCodeBlocks(text)
        text = self._DoBlockQuotes(text)

    	# We did this in parse()
    	# to escape the source
    	# now it's stuff _we_ made
    	# so we don't wrap it in <p>s.
        text = self._HashHTMLBlocks(text)
        text = self._FormParagraphs(text)
        return text

    r_NewLine = re.compile(" {2,}\n")
    def _RunSpanGamut(self, text):
        text = self._DoCodeSpans(text)
        text = self._EscapeSpecialChars(text)
        text = self._DoImages(text)
        text = self._DoAnchors(text)
        text = self._DoAutoLinks(text)
        text = self._EncodeAmpsAndAngles(text)
        text = self._DoItalicsAndBold(text)
        text = self.r_NewLine.sub(" <br%s\n" % self.emptyelt, text)
        return text

    def _EscapeSpecialChars(self, text):
        tokens = self._TokenizeHTML(text)
        text = ""
        for cur_token in tokens:
            if cur_token[0] == "tag":
                cur_token[1] = cur_token[1].replace('*', self.escapetable["*"])
                cur_token[1] = cur_token[1].replace('_', self.escapetable["_"])
                text += cur_token[1]
            else:
                text += self._EncodeBackslashEscapes(cur_token[1])
        return text

    r_DoAnchors1 = re.compile(
          r""" (                 # wrap whole match in $1
                  \[
                    (.*?)        # link text = $2 
                    # [for bracket nesting, see below]
                  \]

                  [ ]?           # one optional space
                  (?:\n[ ]*)?    # one optional newline followed by spaces

                  \[
                    (.*?)        # id = $3
                  \]
                )
    """, re.S|re.VERBOSE)
    r_DoAnchors2 = re.compile(
          r""" (                   # wrap whole match in $1
                  \[
                    (.*?)          # link text = $2
                  \]
                  \(               # literal paren
                        [ \t]*
                        <?(.+?)>?  # href = $3
                        [ \t]*
                        (          # $4
                          ([\'\"]) # quote char = $5
                          (.*?)    # Title = $6
                          \5       # matching quote
                        )?         # title is optional
                  \)
                )
    """, re.S|re.VERBOSE)
    def _DoAnchors(self, text): 
        # We here don't do the same as the perl version, as python's regex
        # engine gives us no way to match brackets.

        def handler1(m):
            whole_match = m.group(1)
            link_text = m.group(2)
            link_id = m.group(3).lower()
            if not link_id: link_id = link_text.lower()
            title = self.titles.get(link_id, None)
                

            if self.urls.has_key(link_id):
                url = self.urls[link_id]
                url = url.replace("*", self.escapetable["*"])
                url = url.replace("_", self.escapetable["_"])
                res = '<a href="%s"' % htmlquote(url)

                if title:
                    title = title.replace("*", self.escapetable["*"])
                    title = title.replace("_", self.escapetable["_"])
                    res += ' title="%s"' % htmlquote(title)
                res += ">%s</a>" % htmlquote(link_text)
            else:
                res = whole_match
            return res

        def handler2(m):
            whole_match = m.group(1)
            link_text = m.group(2)
            url = m.group(3)
            title = m.group(6)

            url = url.replace("*", self.escapetable["*"])
            url = url.replace("_", self.escapetable["_"])
            res = '''<a href="%s"''' % htmlquote(url)
            
            if title:
                title = title.replace('"', '&quot;')
                title = title.replace("*", self.escapetable["*"])
                title = title.replace("_", self.escapetable["_"])
                res += ' title="%s"' % htmlquote(title)
            res += ">%s</a>" % htmlquote(link_text)
            return res

        text = self.r_DoAnchors1.sub(handler1, text)
        text = self.r_DoAnchors2.sub(handler2, text)
        return text

    r_DoImages1 = re.compile(
           r""" (                       # wrap whole match in $1
                  !\[
                    (.*?)               # alt text = $2
                  \]

                  [ ]?                  # one optional space
                  (?:\n[ ]*)?           # one optional newline followed by spaces

                  \[
                    (.*?)               # id = $3
                  \]

                )
    """, re.VERBOSE|re.S)

    r_DoImages2 = re.compile(
          r""" (                        # wrap whole match in $1
                  !\[
                    (.*?)               # alt text = $2
                  \]
                  \(                    # literal paren
                        [ \t]*
                        <?(\S+?)>?      # src url = $3
                        [ \t]*
                        (               # $4
                        ([\'\"])        # quote char = $5
                          (.*?)         # title = $6
                          \5            # matching quote
                          [ \t]*
                        )?              # title is optional
                  \)
                )
    """, re.VERBOSE|re.S)

    def _DoImages(self, text):
        def handler1(m):
            whole_match = m.group(1)
            alt_text = m.group(2)
            link_id = m.group(3).lower()

            if not link_id:
                link_id = alt_text.lower()

            alt_text = alt_text.replace('"', "&quot;")
            if self.urls.has_key(link_id):
                url = self.urls[link_id]
                url = url.replace("*", self.escapetable["*"])
                url = url.replace("_", self.escapetable["_"])
                res = '''<img src="%s" alt="%s"''' % (htmlquote(url), htmlquote(alt_text))
                if self.titles.has_key(link_id):
                    title = self.titles[link_id]
                    title = title.replace("*", self.escapetable["*"])
                    title = title.replace("_", self.escapetable["_"])
                    res += ' title="%s"' % htmlquote(title)
                res += self.emptyelt
            else:
                res = whole_match
            return res

        def handler2(m):
            whole_match = m.group(1)
            alt_text = m.group(2)
            url = m.group(3)
            title = m.group(6) or ''
            
            alt_text = alt_text.replace('"', "&quot;")
            title = title.replace('"', "&quot;")
            url = url.replace("*", self.escapetable["*"])
            url = url.replace("_", self.escapetable["_"])
            res = '<img src="%s" alt="%s"' % (htmlquote(url), htmlquote(alt_text))
            if title is not None:
                title = title.replace("*", self.escapetable["*"])
                title = title.replace("_", self.escapetable["_"])
                res += ' title="%s"' % htmlquote(title)
            res += self.emptyelt
            return res

        text = self.r_DoImages1.sub(handler1, text)
        text = self.r_DoImages2.sub(handler2, text)
        return text
    
    r_DoHeaders = re.compile(r"^(\#{1,6})[ \t]*(.+?)[ \t]*\#*\n+", re.VERBOSE|re.M)
    def _DoHeaders(self, text):
        def findheader(text, c, n):
            textl = text.split('\n')
            for i in xrange(len(textl)):
                if i >= len(textl): continue
                count = textl[i].strip().count(c)
                if count > 0 and count == len(textl[i].strip()) and textl[i+1].strip() == '' and textl[i-1].strip() != '':
                    textl = textl[:i] + textl[i+1:]
                    textl[i-1] = '<h'+n+'>'+self._RunSpanGamut(textl[i-1])+'</h'+n+'>'
                    textl = textl[:i] + textl[i+1:]
            text = '\n'.join(textl)
            return text
        
        def handler(m):
            level = len(m.group(1))
            header = self._RunSpanGamut(m.group(2))
            return "<h%s>%s</h%s>\n\n" % (level, header, level)

        text = findheader(text, '=', '1')
        text = findheader(text, '-', '2')
        text = self.r_DoHeaders.sub(handler, text)
        return text
    
    rt_l = r"""
    (
      (
        [ ]{0,%d}
        ([*+-]|\d+[.])
        [ \t]+
      )
      (?:.+?)
      (
        \Z
      |
        \n{2,}
        (?=\S)
        (?![ \t]* ([*+-]|\d+[.])[ \t]+)
      )
    )
    """ % (tabwidth - 1)
    r_DoLists = re.compile('^'+rt_l, re.M | re.VERBOSE | re.S)
    r_DoListsTop = re.compile(
      r'(?:\A\n?|(?<=\n\n))'+rt_l, re.M | re.VERBOSE | re.S)
    
    def _DoLists(self, text):
        def handler(m):
            list_type = "ol"
            if m.group(3) in [ "*", "-", "+" ]:
                list_type = "ul"
            listn = m.group(1)
            listn = self.r_multiline.sub("\n\n\n", listn)
            res = self._ProcessListItems(listn)
            res = "<%s>\n%s</%s>\n" % (list_type, res, list_type)
            return res
            
        if self.list_level:
            text = self.r_DoLists.sub(handler, text)
        else:
            text = self.r_DoListsTop.sub(handler, text)
        return text

    r_multiend = re.compile(r"\n{2,}\Z")
    r_ProcessListItems = re.compile(r"""
    (\n)?                            # leading line = $1
    (^[ \t]*)                        # leading whitespace = $2
    ([*+-]|\d+[.]) [ \t]+            # list marker = $3
    ((?:.+?)                         # list item text = $4
    (\n{1,2}))
    (?= \n* (\Z | \2 ([*+-]|\d+[.]) [ \t]+))
    """, re.VERBOSE | re.M | re.S)

    def _ProcessListItems(self, text):
        self.list_level += 1
        text = self.r_multiend.sub("\n", text)
        
        def handler(m):
            item = m.group(4)
            leading_line = m.group(1)
            leading_space = m.group(2)

            if leading_line or self.r_multiline.search(item):
                item = self._RunBlockGamut(self._Outdent(item))
            else:
                item = self._DoLists(self._Outdent(item))
                if item[-1] == "\n": item = item[:-1] # chomp
                item = self._RunSpanGamut(item)
            return "<li>%s</li>\n" % item

        text = self.r_ProcessListItems.sub(handler, text)
        self.list_level -= 1
        return text
    
    r_DoCodeBlocks = re.compile(r"""
    (?:\n\n|\A)
    (                 # $1 = the code block
    (?:
    (?:[ ]{%d} | \t)  # Lines must start with a tab or equiv
    .*\n+
    )+
    )
    ((?=^[ ]{0,%d}\S)|\Z) # Lookahead for non-space/end of doc
    """ % (tabwidth, tabwidth), re.M | re.VERBOSE)
    def _DoCodeBlocks(self, text):
        def handler(m):
            codeblock = m.group(1)
            codeblock = self._EncodeCode(self._Outdent(codeblock))
            codeblock = self._Detab(codeblock)
            codeblock = codeblock.lstrip("\n")
            codeblock = codeblock.rstrip()
            res = "\n\n<pre><code>%s\n</code></pre>\n\n" % codeblock
            return res

        text = self.r_DoCodeBlocks.sub(handler, text)
        return text
    r_DoCodeSpans = re.compile(r"""
    (`+)            # $1 = Opening run of `
    (.+?)           # $2 = The code block
    (?<!`)
    \1              # Matching closer
    (?!`)
    """, re.I|re.VERBOSE)
    def _DoCodeSpans(self, text):
        def handler(m):
            c = m.group(2)
            c = c.strip()
            c = self._EncodeCode(c)
            return "<code>%s</code>" % c

        text = self.r_DoCodeSpans.sub(handler, text)
        return text
    
    def _EncodeCode(self, text):
        text = text.replace("&","&amp;")
        text = text.replace("<","&lt;")
        text = text.replace(">","&gt;")
        for c in "*_{}[]\\":
            text = text.replace(c, self.escapetable[c])
        return text

    
    r_DoBold = re.compile(r"(\*\*|__) (?=\S) (.+?[*_]*) (?<=\S) \1", re.VERBOSE | re.S)
    r_DoItalics = re.compile(r"(\*|_) (?=\S) (.+?) (?<=\S) \1", re.VERBOSE | re.S)
    def _DoItalicsAndBold(self, text):
        text = self.r_DoBold.sub(r"<strong>\2</strong>", text)
        text = self.r_DoItalics.sub(r"<em>\2</em>", text)
        return text
    
    r_start = re.compile(r"^", re.M)
    ####r_DoBlockQuotes1 = re.compile(r"^[ \t]*>[ \t]?", re.M)
    r_DoBlockQuotes1 = re.compile(r"^[ \t]*&gt;[ \t]?", re.M)
    r_DoBlockQuotes2 = re.compile(r"^[ \t]+$", re.M)
    r_DoBlockQuotes3 = re.compile(r"""
    (                       # Wrap whole match in $1
     (
       ^[ \t]*&gt;[ \t]?       # '>' at the start of a line
       .+\n                 # rest of the first line
       (.+\n)*              # subsequent consecutive lines
       \n*                  # blanks
      )+
    )""", re.M | re.VERBOSE)
    r_protectpre = re.compile(r'(\s*<pre>.+?</pre>)', re.S)
    r_propre = re.compile(r'^  ', re.M)

    def _DoBlockQuotes(self, text):
        def prehandler(m):
            return self.r_propre.sub('', m.group(1))
                
        def handler(m):
            bq = m.group(1)
            bq = self.r_DoBlockQuotes1.sub("", bq)
            bq = self.r_DoBlockQuotes2.sub("", bq)
            bq = self._RunBlockGamut(bq)
            bq = self.r_start.sub("  ", bq)
            bq = self.r_protectpre.sub(prehandler, bq)
            return "<blockquote>\n%s\n</blockquote>\n\n" % bq
            
        text = self.r_DoBlockQuotes3.sub(handler, text)
        return text

    r_tabbed = re.compile(r"^([ \t]*)")
    def _FormParagraphs(self, text):
        text = text.strip("\n")
        grafs = self.r_multiline.split(text)

        for g in xrange(len(grafs)):
            t = grafs[g].strip() #@@?
            if not self.html_blocks.has_key(t):
                t = self._RunSpanGamut(t)
                t = self.r_tabbed.sub(r"<p>", t)
                t += "</p>"
                grafs[g] = t

        for g in xrange(len(grafs)):
            t = grafs[g].strip()
            if self.html_blocks.has_key(t):
                grafs[g] = self.html_blocks[t]
        
        return "\n\n".join(grafs)

    r_EncodeAmps = re.compile(r"&(?!#?[xX]?(?:[0-9a-fA-F]+|\w+);)")
    r_EncodeAngles = re.compile(r"<(?![a-z/?\$!])")
    def _EncodeAmpsAndAngles(self, text):
        text = self.r_EncodeAmps.sub("&amp;", text)
        text = self.r_EncodeAngles.sub("&lt;", text)
        return text

    def _EncodeBackslashEscapes(self, text):
        for char in self.escapechars:
            text = text.replace("\\" + char, self.escapetable[char])
        return text
    
    r_link = re.compile(r"<((https?|ftp):[^\'\">\s]+)>", re.I)
    r_email = re.compile(r"""
      <
      (?:mailto:)?
      (
         [-.\w]+
         \@
         [-a-z0-9]+(\.[-a-z0-9]+)*\.[a-z]+
      )
      >""", re.VERBOSE|re.I)
    def _DoAutoLinks(self, text):
        text = self.r_link.sub(r'<a href="\1">\1</a>', text)

        def handler(m):
            l = m.group(1)
            return self._EncodeEmailAddress(self._UnescapeSpecialChars(l))
    
        text = self.r_email.sub(handler, text)
        return text
    
    r_EncodeEmailAddress = re.compile(r">.+?:")
    def _EncodeEmailAddress(self, text):
        encode = [
            lambda x: "&#%s;" % ord(x),
            lambda x: "&#x%X;" % ord(x),
            lambda x: x
        ]

        text = "mailto:" + text
        addr = ""
        for c in text:
            if c == ':': addr += c; continue
            
            r = semirandom(addr)
            if r < 0.45:
                addr += encode[1](c)
            elif r > 0.9 and c != '@':
                addr += encode[2](c)
            else:
                addr += encode[0](c)

        text = '<a href="%s">%s</a>' % (addr, addr)
        text = self.r_EncodeEmailAddress.sub('>', text)
        return text

    def _UnescapeSpecialChars(self, text):
        for key in self.escapetable.keys():
            text = text.replace(self.escapetable[key], key)
        return text
    
    tokenize_depth = 6
    tokenize_nested_tags = '|'.join([r'(?:<[a-z/!$](?:[^<>]'] * tokenize_depth) + (')*>)' * tokenize_depth)
    r_TokenizeHTML = re.compile(
      r"""(?: <! ( -- .*? -- \s* )+ > ) |  # comment
          (?: <\? .*? \?> ) |              # processing instruction
          %s                               # nested tags
    """ % tokenize_nested_tags, re.I|re.VERBOSE)
    def _TokenizeHTML(self, text):
        pos = 0
        tokens = []
        matchobj = self.r_TokenizeHTML.search(text, pos)
        while matchobj:
            whole_tag = matchobj.string[matchobj.start():matchobj.end()]
            sec_start = matchobj.end()
            tag_start = sec_start - len(whole_tag)
            if pos < tag_start:
                tokens.append(["text", matchobj.string[pos:tag_start]])

            tokens.append(["tag", whole_tag])
            pos = sec_start
            matchobj = self.r_TokenizeHTML.search(text, pos)

        if pos < len(text):
            tokens.append(["text", text[pos:]])
        return tokens

    r_Outdent = re.compile(r"""^(\t|[ ]{1,%d})""" % tabwidth, re.M)
    def _Outdent(self, text):
        text = self.r_Outdent.sub("", text)
        return text    

    def _Detab(self, text): return text.expandtabs(self.tabwidth)

def Markdown(*args, **kw): return _Markdown().parse(*args, **kw)
markdown = Markdown

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print Markdown(open(sys.argv[1]).read())
    else:
        print Markdown(sys.stdin.read())
