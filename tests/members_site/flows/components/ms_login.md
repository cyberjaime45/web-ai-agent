# Members Site Login

## Steps
- goto: "<MEMBERS_SITE_URL>"
- wait_load
<!-- - click: "Accept All Cookies" -->
- fill: "[data-testid='email-login-input']" | "core@test.com"
- fill: "[data-testid='password-login-input']" | "Welcome1!"
- click: "SIGN IN"
- wait_load