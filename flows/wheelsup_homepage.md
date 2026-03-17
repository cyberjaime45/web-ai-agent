# WheelsUp Homepage

## Config
- url: https://wheelsup.com/
- timeout: 30000

## Steps

1. open "https://wheelsup.com/"
2. wait_for_load
3. assert_title "WheelsUp"
4. screenshot "wu_homepage"
5. scroll down
6. screenshot "wu_homepage_scrolled"
7. scroll up

## Expected Outcome
- WheelsUp homepage loads successfully
- Page title contains "WheelsUp"
