# FMS MVC Smoke Tests
markers: smoke, non_destructive

## Login Page
- run_flow: "components/sso_login"
- wait_load

## Home Page
- goto: "{FMS_URL}"
- wait_load
- assert_text: "My Tasks"
- assert_text: "My Schedule"
- screenshot
## Schedule Page
- goto: "{FMS_URL}/calendar/scheduleboard/"
- wait_load
- wait_for_element: "#divTimeline"
- screenshot
## Leads Page
- goto: "{FMS_URL}/leads"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Opportunity Page
- goto: "{FMS_URL}/opportunity"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Quote Page
- goto: "{FMS_URL}/quote"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Operations Page
- goto: "{FMS_URL}/operations?tab=dashboard"
- wait_load
- assert_text: "DEPARTING 48 HRS"
- screenshot
## Trip Search Page
- goto: "{FMS_URL}/operations?tab=flightsearch"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Feasibility Page
- goto: "{FMS_URL}/portal/operations/feasibility"
- wait_load
- assert_text: "Feasibility"
- wait: 5000
- screenshot
## Aircraft Page
- goto: "{FMS_URL}/aircraft?tab=search"
- wait_load
- wait_for_element: "#dtResults"
- screenshot
## Fleet Page
- goto: "{FMS_URL}/aircraft?tab=fleet"
- wait_load
- assert_text: "Automation_F01"
- screenshot
## Discrepancy Page
- goto: "{FMS_URL}/discrepancy"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Inspections Page
- goto: "{FMS_URL}/inspectionitem"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Job Cards Page
- goto: "{FMS_URL}/jobcards"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Integration Page
- goto: "{FMS_URL}/maintenance/integration"
- wait_load
- assert_text: "Logs"
- screenshot
## Reports Page (Fleet)
- goto: "{FMS_URL}/portal/reporting/AircraftFleet"
- wait_load
- assert_visible: "iframe[class='reportClass']"
- screenshot
## Personnel Page
- goto: "{FMS_URL}/personnel"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## FSI Logs Page
- goto: "{FMS_URL}/fsi/integration"
- wait_load
- assert_visible: "#dtPostLogBook_wrapper"
- screenshot
## Programs Page
- goto: "{FMS_URL}/programs"
- wait_load
- assert_visible: "Create New"
- screenshot
## Training Items Page
- goto: "{FMS_URL}/crewrecords"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Accounts Page
- goto: "{FMS_URL}/accounts"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Contacs Page
- goto: "{FMS_URL}/contacts"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Cases Page
- goto: "{FMS_URL}/casemanagement"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Vendor/Aircraft Page
- goto: "{FMS_URL}/vendors?tab=vendors"
- wait_load
- assert_visible: "#dtResults"
- screenshot
## Argus Page
- goto: "{FMS_URL}/argus"
- wait_load
- assert_text: "Aircraft Model Mapping"
- screenshot
## Avinode Page
- goto: "{FMS_URL}/avinode"
- wait_load
- assert_text: "Avinode"
- screenshot
## Fsi Page
- goto: "{FMS_URL}/fsi"
- wait_load
- assert_text: "Aircraft Model Mapping"
- screenshot
## Foreflight Page
- goto: "{FMS_URL}/foreflight"
- wait_load
- assert_text: "Configuration"
- screenshot
## Airports Page
- goto: "{FMS_URL}/airports"
- wait_load
- assert_visible: "#mapDiv"
- screenshot
## Notes Page
- goto: "{FMS_URL}/airports/notes"
- wait_load
- assert_visible: "Create New"
- screenshot
## Company Page
- goto: "{FMS_URL}/company"
- wait_load
- assert_visible: "OPERATOR CERTIFICATE"
- screenshot