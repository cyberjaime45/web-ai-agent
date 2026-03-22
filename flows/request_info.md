# Request Info Page

## Config
- url: https://wheelsup.com/request-info
- timeout: 30000

## Steps
- goto: "https://wheelsup.com/request-info"
- wait_for_load
- click_link_text: "Accept All Cookies"
- assert_text: "Ready to learn even more about Wheels Up?"
- assert_text: "What will be the primary purpose of your Wheels Up flights?"
- click: "Please select one"
- click: "Personal"
- fill: "First Name" | "John"
- fill: "Last Name" | "Smith"
- fill: "Email" | "john_smith7272@wheelsup.com"
- fill: "Phone Number" | "1234567890"
- fill: "Street Address" | "123st Main ave"
- fill: "City" | "New York"
- click: "Please select one"
- click: "NY"
- fill: "Zip Code" | "10001"
- fill: "Country" | "United States"
- click: "div.listinputselect .containerover"
- fill: "Preferred Airports" | "KACK"
- click: "Please select one"
- click: "Event"
- fill: ".textarea-box" | "I need to part of the wheelsup family"
- click: "#acceptWUPPrivacyPolicy-clone div.listinputselect .containerover"
- screenshot