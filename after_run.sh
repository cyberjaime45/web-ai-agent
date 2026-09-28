# Navigate to the reports directory and zip the production reports folder before cleaning up.
cd $BUILD_SOURCESDIRECTORY/reports/

echo "Populating total count from JSON file"
run_id=$(jq -r '.run_id' ${ENVIRONMENT}/summary.json)
build_name=$(jq -r '.environment.run_id' ${ENVIRONMENT}/summary.json)
total_count=$(jq -r '.totals.total' ${ENVIRONMENT}/summary.json)
pass_rate=$(jq -r '.totals.pass_rate' ${ENVIRONMENT}/summary.json)

#Validating if the report has actual data
if [ "$total_count" -eq 0 ]; then
  echo "##vso[task.logissue type=error]Report has no data: total_count=$total_count, pass_rate=$pass_rate"
  echo "Error: total_count ($total_count) or pass_rate ($pass_rate) is zero. Aborting upload."
  exit 1
fi

echo "Zipping reports folder"   
zipFileName=${run_id}
fileExt=".zip"
zipName=$zipFileName$fileExt

# Create a zip archive of the production reports folder
zip -r -q $zipName "${ENVIRONMENT}/"
echo "Created zip archive: $zipName"

sleep 2s

upload_url="https://automation.wheelsup.com/api/reports/simple-upload"
payload=$(cat <<EOF
{
  "script": "${WEB_APP}"
}
EOF
)

echo "Uploading reports to Dashboard"
echo "Upload URL: $upload_url"
echo "Payload: $payload"
retry_count=0
max_retries=3
success=false
while [ $retry_count -lt $max_retries ]; do
  response=$(curl --location --request POST "$upload_url" \
    --header "Key: kwg2sJTirUddsSW" \
    --form "file=@$zipName" \
    --form "payload=$payload" \
    --write-out "HTTPSTATUS:%{http_code}" --silent)

    http_body=$(echo "$response" | sed -e 's/HTTPSTATUS\:.*//g')
    http_status=$(echo "$response" | tr -d '\n' | sed -e 's/.*HTTPSTATUS://')

    if [ "$http_status" -eq 200 ] || [ "$http_status" -eq 201 ]; then
      echo "Response: $http_body"
      echo "Upload successful!"
      success=true
      break
    else
      echo "Upload failed with status code $http_status. Retrying in 10 seconds... ($((retry_count+1))/$max_retries)"
      echo "##vso[task.logissue type=warning]Upload failed with status code $http_status. Retrying in 10 seconds... ($((retry_count+1))/$max_retries)"
      echo "Response body: $http_body"
      sleep 10
    fi
    retry_count=$((retry_count+1))
done

if [ "$success" = false ]; then
  echo "Failed to upload report after $max_retries attempts."
  echo "##vso[task.logissue type=error]Failed to upload report after $max_retries attempts."
  exit 1
fi

echo "Deleting unused junk files"
rm -rf *