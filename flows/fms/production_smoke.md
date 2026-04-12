# FMS Dashboard Page

## Dashboard Page
- run_flow: "../components/login/sso_login"
- assert_text: "My Tasks"
- assert_text: "My Schedule"
## Schedule Page
- goto: "https://one.wheelsup.com/calendar/scheduleboard/"
- wait_load
- wait_for_element: "#divTimeline"