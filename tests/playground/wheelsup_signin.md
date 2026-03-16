# WheelsUp Sign In Page

## Config
- url: https://wheelsup.com/
- timeout: 30000

## Steps

1. open "https://wheelsup.com/"
2. wait_for_load
3. screenshot "wu_signin_start"
4. click "Sign In"
5. wait_for_load
6. screenshot "wu_signin_page"
7. assert_url "login"
8. wait_for_element "input[type=email], input[type=text], #email, #username"
9. screenshot "wu_signin_form"

## Expected Outcome
- Clicking "Sign In" navigates to the authentication page
- Login form is present and visible
- URL contains "login" or similar auth path

## Notes
- Does NOT submit credentials — read-only navigation test
- wait_for_element uses CSS selector for robustness
