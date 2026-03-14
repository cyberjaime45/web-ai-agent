# Form Validation Flow

## Target Application
- **URL**: https://practicetestautomation.com/practice-test-login/
- **Description**: Test form validation by submitting empty or invalid data

## Credentials
- **Username**: wronguser
- **Password**: wrongpass

## Steps

1. Navigate to the login page
2. Leave both fields empty and click "Submit"
3. Verify an error message appears
4. Fill in the username with "wronguser" and password with "wrongpass"
5. Click "Submit"
6. Verify an error message appears indicating invalid credentials

## Expected Outcome
- Error message is displayed for invalid credentials
- The page does NOT navigate to a success page
- URL should still contain "practice-test-login"

## Error Scenarios
- If the page navigates away on invalid credentials, this is a bug
