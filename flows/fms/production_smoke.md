# FMS MVC Smoke Tests

## Login Page
- run_flow: "../components/login/sso_login"
- wait_load

## Home Page
- goto: "https://one.wheelsup.com/home"
- wait_load
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
- wait: 5000
- screenshot
## Aircraft Page
- goto: "https://one.wheelsup.com/aircraft?tab=search"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Fleet Page
- goto: "https://one.wheelsup.com/aircraft?tab=fleet"
- wait_load
- assert_text: "Automation_F01"
- screenshot
## Discrepancy Page
- goto: "https://one.wheelsup.com/discrepancy"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Inspections Page
- goto: "https://one.wheelsup.com/inspectionitem"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Job Cards Page
- goto: "https://one.wheelsup.com/jobcards"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Integration Page
- goto: "https://one.wheelsup.com/maintenance/integration"
- wait_load
- assert_text: "Logs"
- screenshot
## Reports Page (Fleet)
- goto: "https://one.wheelsup.com/portal/reporting/AircraftFleet"
- wait_load
- assert_visible: "iframe[class='reportClass']"
- screenshot
## Personnel Page
- goto: "https://one.wheelsup.com/personnel"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## FSI Logs Page
- goto: "https://one.wheelsup.com/fsi/integration"
- wait_load
- assert_visible: "#dtPostLogBook_wrapper"
- screenshot
## Programs Page
- goto: "https://one.wheelsup.com/programs"
- wait_load
- assert_visible: "Create New"
- screenshot
## Training Items Page
- goto: "https://one.wheelsup.com/crewrecords"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Accounts Page
- goto: "https://one.wheelsup.com/accounts"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Contacs Page
- goto: "https://one.wheelsup.com/contacts"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Cases Page
- goto: "https://one.wheelsup.com/casemanagement"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Vendor/Aircraft Page
- goto: "https://one.wheelsup.com/vendors?tab=vendors"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Argus Page
- goto: "https://one.wheelsup.com/argus"
- wait_load
- assert_text: "Aircraft Model Mapping"
- screenshot
## Avinode Page
- goto: "https://one.wheelsup.com/avinode"
- wait_load
- assert_text: "Avinode"
- screenshot
## Fsi Page
- goto: "https://one.wheelsup.com/fsi"
- wait_load
- assert_text: "Aircraft Model Mapping"
- screenshot
## Foreflight Page
- goto: "https://one.wheelsup.com/foreflight"
- wait_load
- assert_text: "Configuration"
- screenshot
## Airports Page
- goto: "https://one.wheelsup.com/airports"
- wait_load
- assert_visible: "#mapDiv"
- screenshot
## Notes Page
- goto: "https://one.wheelsup.com/airports/notes"
- wait_load
- assert_visible: "Create New"
- screenshot
## Company Page
- goto: "https://one.wheelsup.com/company"
- wait_load
- assert_visible: "OPERATOR CERTIFICATE"
- screenshot