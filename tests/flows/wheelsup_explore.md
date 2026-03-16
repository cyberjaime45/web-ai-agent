# WheelsUp Explore

## Config
- url: https://wheelsup.com/
- timeout: 30000

## Steps

1. open "https://wheelsup.com/"
2. wait_for_load
3. click_link "Accept All Cookies"
4. assert_text "WheelsUp"
5. click_link "CHARTER UP"
6. wait_for_load
8. assert_url "charter-upp"
9. screenshot "wu_explore_charter_up_page"

## Expected Outcome
- WheelsUp homepage loads and displays brand name
- Charter Up section is accessible via navigation
- Charter Up page URL contains "charter_up"

## Notes
- Layer 2 fallback handles case variations in nav link text
- Screenshot at each major step for audit trail
