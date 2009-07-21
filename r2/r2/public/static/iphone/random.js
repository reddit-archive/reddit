quoteList = new Array();quoteList[0] = "(like a Polaroid picture)";quoteList[1] = "(but don't break it -- it took Steve 9 months to make it)";quoteList[2] = "(like a salt shaker)";
quoteList[3] = "(like a pom pom)";
quoteList[4] = "(like a British nanny)";
quoteList[5] = "(like a mystery present)";
quoteList[6] = "(like a monkey with a puzzle)";
quoteList[7] = "(like a tiny Etch-A-Sketch)";
quoteList[8] = "(like a British nanny)";
quoteList[9] = "(with gusto!)";
quoteList[10] = "(like you're trying to get the last crumbs from the Doritos bag)";
quoteList[11] = "(instead of going to the gym)";
quoteList[12] = "(like Shakira)";


//randomization	var now = new Date();	var secs = now.getSeconds();	var raw_random_number = Math.random(secs);	var random_number = Math.round(raw_random_number * (quoteList.length));	if (random_number == quoteList.length){random_number = 0}			//set quote	var quote = quoteList[random_number];