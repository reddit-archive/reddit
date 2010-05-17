. tests/functions.sh

title "paragraph flow"

rc=0
MARKDOWN_FLAGS=

try 'header followed by paragraph' \
    '###Hello, sailor###
And how are you today?' \
    '<h3>Hello, sailor</h3>

<p>And how are you today?</p>'

try 'two lists punctuated with a HR' \
    '* A
* * *
* B
* C' \
    '<ul>
<li>A</li>
</ul>


<hr />

<ul>
<li>B</li>
<li>C</li>
</ul>'

summary $0
exit $rc
