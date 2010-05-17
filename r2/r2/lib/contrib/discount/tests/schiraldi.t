. tests/functions.sh

title "Bugs & misfeatures reported by Mike Schiraldi"

rc=0
MARKDOWN_FLAGS=

try -fnohtml 'breaks with -fnohtml' 'foo  
bar' '<p>foo<br/>
bar</p>'

try 'links with trailing \)' \
    '[foo](http://en.wikipedia.org/wiki/Link_(film\))' \
    '<p><a href="http://en.wikipedia.org/wiki/Link_(film)">foo</a></p>'

try -fautolink '(url) with -fautolink' \
    '(http://tsfr.org)' \
    '<p>(<a href="http://tsfr.org">http://tsfr.org</a>)</p>'

try 'single #' \
    '#' \
    '<p>#</p>'

try -frelax '* processing with -frelax' \
    '2*4 = 8 * 1 = 2**3' \
    '<p>2*4 = 8 * 1 = 2**3</p>'

try -fnopants '[]() with a single quote mark' \
    '[Poe'"'"'s law](http://rationalwiki.com/wiki/Poe'"'"'s_Law)' \
    '<p><a href="http://rationalwiki.com/wiki/Poe'"'"'s_Law">Poe'"'"'s law</a></p>'

try -fautolink 'autolink url with escaped spaces' \
    'http://\(here\ I\ am\)' \
    '<p><a href="http://(here%20I%20am)">http://(here I am)</a></p>'

try -fautolink 'autolink café_racer' \
    'http://en.wikipedia.org/wiki/café_racer' \
    '<p><a href="http://en.wikipedia.org/wiki/caf%C3%A9_racer">http://en.wikipedia.org/wiki/caf%C3%A9_racer</a></p>'

try -fautolink 'autolink url with arguments' \
    'http://foo.bar?a&b=c' \
    '<p><a href="http://foo.bar?a&amp;b=c">http://foo.bar?a&amp;b=c</a></p>'

try '\( escapes in []()' \
    '[foo](http://a.com/\(foo\))' \
    '<p><a href="http://a.com/(foo)">foo</a></p>'

try -fautolink 'autolink url with escaped ()' \
    'http://a.com/\(foo\)' \
    '<p><a href="http://a.com/(foo)">http://a.com/(foo)</a></p>'

try -fautolink 'autolink url with escaped \' \
    'http://a.com/\\\)' \
    '<p><a href="http://a.com/\)">http://a.com/\)</a></p>'

try -fautolink 'autolink url with -' \
    'http://experts-exchange.com' \
    '<p><a href="http://experts-exchange.com">http://experts-exchange.com</a></p>'

try -fautolink 'autolink url with +' \
    'http://www67.wolframalpha.com/input/?i=how+old+was+jfk+jr+when+jfk+died' \
    '<p><a href="http://www67.wolframalpha.com/input/?i=how+old+was+jfk+jr+when+jfk+died">http://www67.wolframalpha.com/input/?i=how+old+was+jfk+jr+when+jfk+died</a></p>'

try -fautolink 'autolink url with &' \
    'http://foo.bar?a&b=c' \
    '<p><a href="http://foo.bar?a&amp;b=c">http://foo.bar?a&amp;b=c</a></p>'

    
try -fautolink 'autolink url with ,' \
    'http://www.spiegel.de/international/europe/0,1518,626171,00.html' \
    '<p><a href="http://www.spiegel.de/international/europe/0,1518,626171,00.html">http://www.spiegel.de/international/europe/0,1518,626171,00.html</a></p>'

try -fautolink 'autolink url with : & ;' \
    'http://www.biblegateway.com/passage/?search=Matthew%205:29-30;&version=31;' \
    '<p><a href="http://www.biblegateway.com/passage/?search=Matthew%205:29-30;&amp;version=31;">http://www.biblegateway.com/passage/?search=Matthew%205:29-30;&amp;version=31;</a></p>'

Q="'"
try -fautolink 'security hole with \" in []()' \
'[XSS](/ "\"=\"\"onmouseover='$Q'alert(String.fromCharCode(88,83,83))'$Q'")' \
'<p><a href="/" title="\&quot;=\&quot;\&quot;onmouseover='$Q'alert(String.fromCharCode(88,83,83))'$Q'">XSS</a></p>'

try -fautolink 'autolink and prefix fragment' \
'xxxxxxx http://x.com/

xxx xxxxht' \
'<p>xxxxxxx <a href="http://x.com/">http://x.com/</a></p>

<p>xxx xxxxht</p>'

summary $0
exit $rc
