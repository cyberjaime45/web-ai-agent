# WheelsUp Explore Page

## Config
- url: https://wheelsup.com/
- timeout: 30000

## Steps
1. goto: "https://wheelsup.com/"
2. wait_for_load
3. click_link_text: "Accept All Cookies"
4. assert_text: "WheelsUp"
5. assert_text: "The Next Wave of Private Aviation Is Here"
6. assert_text: "The right way"
7. assert_text: "Cargo charter, without compromise."
8. assert_visible: "Privacy Policy"
