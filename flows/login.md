# Login Page

## Config
- url: https://practicetestautomation.com/practice-test-login/
- timeout: 30000

## Credentials
- username: student
- password: Password123

## Steps
1. goto: "https://practicetestautomation.com/practice-test-login/"
2. wait_for_load
3. fill: "Username" | "student"
4. fill: "Password" | "Password123"
5. click: "Submit"
6. wait_for_url: "logged-in-successfully"
7. assert_text: "Congratulations"

## Expected Outcome
- User is redirected to a success page
- Page displays "Congratulations" or "successfully logged in"
