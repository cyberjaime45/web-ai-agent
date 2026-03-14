# Multi-Page Journey Flow

## Target Application
- **URL**: https://practicetestautomation.com/
- **Description**: Full end-to-end journey spanning multiple pages: Home → Practice → Login → Success. The agent must autonomously discover navigation elements and verify state at each page boundary.

## Credentials
- **Username**: student
- **Password**: Password123

## Steps

1. Navigate to the home page
2. Verify the page title contains "Practice Test Automation"
3. Click the "Practice" navigation link
4. Verify the URL contains "practice"
5. Click the "Test Login" link
6. Verify the URL contains "practice-test-login"
7. Enter the username into the "Username" field
8. Enter the password into the "Password" field
9. Click the "Submit" button
10. Verify the URL contains "logged-in-successfully"
11. Verify the page contains text "Congratulations"

## Expected Outcome
- Successfully navigated from Home to Practice page
- Successfully navigated from Practice to Login page
- Login succeeded with valid credentials
- Final URL contains "logged-in-successfully"
- A message containing "Congratulations" is visible on the success page

## Error Scenarios
- If the Practice link is not found on the home page, the flow fails
- If the Test Login link is not found on the Practice page, the flow fails
- If login fails with valid credentials, it is a site defect
- If the success page does not contain "Congratulations", the assertion fails

## Notes
- This flow exercises multi-page navigation with persistent browser state across pages
- The agent must autonomously identify clickable elements at each step
- At least three distinct page loads (Home, Practice, Login) occur before the final assertion
- Use screenshots to create an audit trail at each major page transition
