# Home Page
This is the home page for the marketing site

## Test One
markers: smoke, regression
- goto: "https://wheelsup.com/"
- wait_load
- click_link_text: "Accept All Cookies"
- assert_text: "WheelsUp"

## Test Two
markers: another_tag
- goto: "https://wheelsup.com/"
- wait_load
- click_link_text: "Accept All Cookies"
- assert_text: "WheelsUp"
