. tests/functions.sh

title "emphasis"

rc=0
MARKDOWN_FLAGS=

try '*hi* -> <em>hi</em>' '*hi*' '<p><em>hi</em></p>'
try '* -> *' 'A * A' '<p>A * A</p>'
try -fstrict '***A**B*' '***A**B*' '<p><em><strong>A</strong>B</em></p>'
try -fstrict '***A*B**' '***A*B**' '<p><strong><em>A</em>B</strong></p>'
try -fstrict '**A*B***' '**A*B***' '<p><strong>A<em>B</em></strong></p>'
try -fstrict '*A**B***' '*A**B***' '<p><em>A<strong>B</strong></em></p>'

if ./markdown -V | grep RELAXED >/dev/null; then
    try -frelax '_A_B with -frelax' '_A_B' '<p>_A_B</p>'
    try -fstrict '_A_B with -fstrict' '_A_B' '<p><em>A</em>B</p>'
fi

summary $0
exit $rc
