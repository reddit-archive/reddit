. tests/functions.sh

title "pandoc headers"

rc=0
MARKDOWN_FLAGS=

HEADER='% title
% author(s)
% date'


if ./markdown -V | grep HEADER > /dev/null; then

    try 'valid header' "$HEADER" ''
    try -F0x0100 'valid header with -F0x0100' "$HEADER" '<p>% title
% author(s)
% date</p>'

    try 'invalid header' \
	'% title
% author(s)
a pony!' \
	'<p>% title
% author(s)
a pony!</p>'

    try 'offset header' \
	'
% title
% author(s)
% date' \
	'<p>% title
% author(s)
% date</p>'

    try 'indented header' \
	'  % title
% author(s)
% date' \
	'<p>  % title
% author(s)
% date</p>'

else

    try 'ignore headers' "$HEADER" '<p>% title
% author(s)
% date</p>'

fi

summary $0
exit $rc
