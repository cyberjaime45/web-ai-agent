# FMS MVC Smoke Tests

## Dashboard Page
- run_flow: "../components/login/sso_login"
- assert_text: "My Tasks"
- assert_text: "My Schedule"
- screenshot
## Schedule Page
- goto: "https://one.wheelsup.com/calendar/scheduleboard/"
- wait_load
- wait_for_element: "#divTimeline"
- screenshot
## Leads Page
- goto: "https://one.wheelsup.com/leads"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Opportunity Page
- goto: "https://one.wheelsup.com/opportunity"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Quote Page
- goto: "https://one.wheelsup.com/quote"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Operations Page
- goto: "https://one.wheelsup.com/operations?tab=dashboard"
- wait_load
- assert_text: "DEPARTING 48 HRS"
- screenshot
## Trip Search Page
- goto: "https://one.wheelsup.com/operations?tab=flightsearch"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Feasibility Page
- goto: "https://one.wheelsup.com/portal/operations/feasibility"
- wait_load
- assert_text: "Feasibility"
- screenshot
## Aircraft Page
- goto: "https://one.wheelsup.com/aircraft?tab=search"
- wait_load
- wait_for_element: "#dtResults"
- screenshot