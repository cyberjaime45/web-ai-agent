# One Way Bokking

## Credentials
- username: business@wheelsup.com
- timeout: "Welcome1!"

## Steps
- goto: "https://memberssitestaging.wheelsup.com/"
- wait_load
<!-- - click: "Accept All Cookies" -->
- fill: "[data-testid='email-login-input']" | "core@test.com"
- fill: "[data-testid='password-login-input']" | "Welcome1!"
- click: "SIGN IN"
- wait_load
- click: "Book your flight"
- wait_load
<!-- Search form page -->
- click: "One way"
- fill: "Enter airport, city or ZIP" | "KBOS"
- click_link_text: "Boston Logan International"
- fill: "Enter airport, city or ZIP" | "KACK"
- click: "Morristown Municipal"
<!-- Number of passengers -->
- click: "button[tabindex='0'][type='button'][aria-label='+']"
<!-- Number of pets -->
- click: "button[tabindex='0'][type='button'][aria-label='+']"
- click: "Next"
- click: "30"
- click: "Next"
- click: "Search"
<!-- Flight serach results page -->
wait_for_element: "div[data-name='CarouselListSlide']"
- click: "Book"


