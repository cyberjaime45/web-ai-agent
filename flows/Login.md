# Login Flow

## Target Application
- **URL**: https://practicetestautomation.com/practice-test-login/
- **Description**: Practice test automation login page

## Credentials
- **Username**: student
- **Password**: Password123

## Steps

1. Navigate to the login page
2. Enter the username into the "Username" field
3. Enter the password into the "Password" field
4. Click the "Submit" button
5. Verify that the page navigates to a success page
6. Verify the page contains text "Congratulations" or "successfully logged in"

## Expected Outcome
- URL changes to contain "logged-in-successfully"
- A success message is displayed on the page

## Error Scenarios
- If invalid credentials are used, an error message should appear
- The error message should contain "Your username is invalid!" or "Your password is invalid!"
