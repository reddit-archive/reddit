#!/bin/bash

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

files=( psrs.js utils.js animate.js link.js comments.js subreddit.js vote_piece.js reddit_piece.js organic.js )

wd=`pwd`
redditjs='reddit.js'
framejs='frame.js'
votejs='vote.js'
compressor=" $wd/r2/lib/contrib/jsjam -g -i"


echo "generating rtl style sheet"

./rtl.sh


echo "Generating reddit.js..."

cd r2/public/static
[ -e $redditjs ]     && rm $redditjs
[ -e $redditjs-big ] && rm $redditjs-big

cat json.js > $redditjs.tmp
for f in "${files[@]}"
do 
    $compressor $f >> $redditjs.tmp
done;
sed 's/\$/ \$/g' $redditjs.tmp > $redditjs


echo "Generating vote.js..."
# compress the votes alone (for buttons)
cat psrs.js | $compressor | sed 's/\$/ \$/g' > $votejs
cat utils.js vote_piece.js | $compressor >> $votejs

echo "Generating frame.js..."
# compress frame alone (for the toolbar)
cat psrs.js > $framejs
cat vote_piece.js utils.js frame_piece.js | $compressor >> $framejs

echo "droppping md5s..."
for file in *.js
do
    cat $file | openssl md5  > $file.md5
done
for file in *.css
do
    cat $file | openssl md5  > $file.md5
done
