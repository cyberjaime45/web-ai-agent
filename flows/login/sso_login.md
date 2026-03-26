# SSO Login Page

## Steps
- goto: "https://one-staging.wheelsup.com/"
- wait_for_text: "Sign in"
- click: " Sign in with SSO"
- fill: "input[type='email']" | "<FMS_EMAIL>"
- click: "Next"
- fill: "Password" | "<FMS_PASSWORD>"
- click: "Sign in"
- click: "Yes"