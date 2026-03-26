# Members Site Login

## Steps
- goto: "https://memberssitestaging.wheelsup.com/"
- wait_load
<!-- - click: "Accept All Cookies" -->
- fill: "[data-testid='email-login-input']" | "core@test.com"
- fill: "[data-testid='password-login-input']" | "Welcime1!"
- click: "SIGN IN"
- wait_load