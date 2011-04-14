$(document).ready(function() {
	/* 	Expando dropdowns and whatnot for the launch page */
/*	$(".col-trigger").click( function() {
		//Show the other columns, while hiding the expando
		if ( $(this).parent().hasClass("shown") ) {
			$(this).parent().siblings(".column").animate({
					width: 'show',
					height: 'show',
				}, 500 );
			;
			$(this).parent().removeClass("shown");
			$(this).siblings(".col-expando").animate({
				width: 'hide',
				height: 'hide',
				}, 500 );
		} else { //Hide the other columns while showing the expando
 			$(this).parent().siblings(".column").animate({
 					width: 'hide',
 					height: 'hide',
 				}, 500 );
			$(this).parent().addClass("shown");
			$(this).siblings(".col-expando").animate({
					width: 'show',
					height: 'show',
				}, 500 );
		}
	} );
	$(".col-expando-close").click( function() {
		//Hide the parent expando
		$(this).parent().animate({
				width: 'hide',
				height: 'hide',
				}, 500 );
		//Expand the other columns
		$(this).parent().parent().siblings('.column').animate({
					width: 'show',
					height: 'show',
				}, 500 );

		//Remove shown from this column
		$(this).parent().parent().removeClass("shown");

	});*/
	$("#testimonial-holder").cycle({
        timeout: 5000,
        delay: 3000,
        pause: 1,
        random: 1
	});
} );