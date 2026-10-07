# One Way Bokking
This is one way booking flow

## Steps
- run_flow: "components/ms_login"
- click: "Book your flight"
- wait_load
<!-- Search form page -->
- click: "One way"
- type: "Enter airport, city or ZIP" | "KBOS"
- click: "Boston Logan International"
- type: "Enter airport, city or ZIP" | "KMMU"
- click: "Morristown Municipal"
<!-- Number of passengers -->
- click: "button[tabindex='0'][type='button'][aria-label='+']"
<!-- Number of pets -->
- click: "button[tabindex='0'][type='button'][aria-label='+']"
- click: "Next"
- click: "12"
- click: "Next"
- click: "Search"
<!-- Flight serach results page -->
wait_for_element: "div[data-name='CarouselListSlide']"
- click: "Book"
<!-- Trip details page -->
- wait_for_text: "Departure time"
- assert_text: "Adding your pets to your passenger list now, will ensure your aircraft and crew are fully prepared to better serve you and your furry friends on your day of travel."
- click: "Review and Pay"
<!-- Checkout flight page -->
- wait_for_text: "Your payment"
- check: "button[aria-checked='false'][data-state='unchecked']" 
- check: "button[aria-checked='false'][data-state='unchecked']"
- click: "BOOK FLIGHT"
<!-- Confirmation page -->
- wait_for_text: "Thank you!"
- assert_text: "Provide all passenger information 24 hours before departure."
- assert_text: "Provide all passenger information 24 hours before departure."
- assert_text: "Arrive at the FBO 30 minutes early to ensure a timely departure."
- screenshot



