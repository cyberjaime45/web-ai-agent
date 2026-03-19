# Home Page

## Config
- url: https://wheelsup.com
- timeout: 30000

## Steps
- goto: "https://wheelsup.com/"
- wait_for_load
- click_link_text: "Accept All Cookies"
- assert_text: "WheelsUp"
- assert_text: "The Next Wave of Private Aviation Is Here"
- assert_text: "The right way"
- assert_text: "Membership that moves you"
- assert_text: "Our new fleet, your next journey"
- assert_text: "The best of both skies"
- assert_text: "Private flying, made simple"
- assert_text: "Group charter, expertly orchestrated"
- assert_text: "Cargo charter, without compromise."
- assert_text: "Cargo charter, without compromise."
- assert_visible: "Privacy Policy"
- assert_text: "855-FLY-8760"
- assert_text: "info@wheelsup.com"
