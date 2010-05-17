. tests/functions.sh

title "xml output with MKD_CDATA"

rc=0
MARKDOWN_FLAGS=

try -fcdata 'xml output from markdown()' 'hello,sailor' '&lt;p&gt;hello,sailor&lt;/p&gt;'
try -fcdata 'from mkd_generateline()' -t'"hello,sailor"' '&amp;ldquo;hello,sailor&amp;rdquo;'
try -fnocdata 'html output from markdown()' '"hello,sailor"' '<p>&ldquo;hello,sailor&rdquo;</p>'
try -fnocdata '... from mkd_generateline()' -t'"hello,sailor"' '&ldquo;hello,sailor&rdquo;'

try -fcdata 'xml output with multibyte utf-8' \
    'tecnología y servicios más confiables' \
    '&lt;p&gt;tecnología y servicios más confiables&lt;/p&gt;'

summary $0
exit $rc
