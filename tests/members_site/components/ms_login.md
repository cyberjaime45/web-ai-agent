# Members Site Login

## Steps
- goto: "{MEMBERS_SITE_URL}"
- wait_load
<!-- - click: "Accept All Cookies" -->
- fill: "[data-testid='email-login-input']" | "{MS_EMAIL}"
- fill: "[data-testid='password-login-input']" | "{MS_PASSWORD}"
- click: "LOG IN"
- wait_load