package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"context"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs/types"
	"github.com/aws/aws-sdk-go-v2/service/secretsmanager"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
)

type Signins struct {
	Cursor   string `json:"cursor"`
	Has_more bool   `json:"has_more"`
	Items    []Item `json:"items"`
}

type TargetUser struct {
	UUID  string `json:"uuid"`
	Name  string `json:"name"`
	Email string `json:"email"`
}

type Client struct {
	AppName         string `json:"app_name"`
	AppVersion      string `json:"app_version"`
	PlatformName    string `json:"platform_name"`
	PlatformVersion string `json:"platform_version"`
	OSName          string `json:"os_name"`
	OSVersion       string `json:"os_version"`
	IPAddress       string `json:"ip_address"`
}

type Location struct {
	Country   string  `json:"country"`
	Region    string  `json:"region"`
	City      string  `json:"city"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
}

type Item struct {
	UUID        string     `json:"uuid"`
	SessionUUID string     `json:"session_uuid"`
	Timestamp   time.Time  `json:"timestamp"`
	Country     string     `json:"country"`
	Category    string     `json:"category"`
	Type        string     `json:"type"`
	Details     string     `json:"details"`
	TargetUser  TargetUser `json:"target_user"`
	Client      Client     `json:"client"`
	Location    Location   `json:"location"`
}

var (
	eventAPIurl        string = "https://events.1password.com"
	region             string = "us-east-1"
	secretName         string = "op-events-api-token"
	parameterName      string = "op-events-api-cursor"
	cloudwatchLogGroup string = "op-events-api-signins"
	cloudwatchStream   string = "op-events-api-signins-stream"
)

func main() {
	lambda.Start(getSignInEvents)
}

// Retrieves data from the sign-in events endpoint. 
// Depending on your implementation you may want to create functions for each of the three endpoints, 
// or refactor this function to accept an endpoint and any other required properties, calling it once for each of the three endpoints. 
func getSignInEvents() {
	api_token := loadToken()
	start_time := time.Now().AddDate(0, 0, -1)

	currCursor := getCursor()

	var payload []byte
	if currCursor == "first_run" || currCursor == "" {
		payload = []byte(fmt.Sprintf(`{
			"limit": 1000,
			"start_time": "%s"
		}`, start_time.Format(time.RFC3339)))
	} else {
		payload = []byte(fmt.Sprintf(`{
			"cursor": "%s"
		}`, currCursor))
	}

	client := &http.Client{}

	signinsRequest, _ := http.NewRequest("POST", fmt.Sprintf("%s/api/v1/signinattempts", eventAPIurl), bytes.NewBuffer(payload))
	signinsRequest.Header.Set("Content-Type", "application/json")
	signinsRequest.Header.Set("Authorization", "Bearer "+api_token)
	signinsResponse, signinsError := client.Do(signinsRequest)
	if signinsError != nil {
		panic(signinsError)
	}
	defer signinsResponse.Body.Close()
	signinsBody, _ := io.ReadAll(signinsResponse.Body)

	var results Signins
	json.Unmarshal(signinsBody, &results)

	if len(results.Items) != 0 {
		writeLogs(results.Items)
		setCursor(results.Cursor)
	}

	if results.Has_more {
		getSignInEvents()
	}
}

func loadConfig() aws.Config {
	config, err := config.LoadDefaultConfig(context.TODO(), config.WithRegion(region))
	if err != nil {
		log.Fatal(err)
	}

	return config
}

func loadToken() string {
	// Create Secrets Manager client
	svc := secretsmanager.NewFromConfig(loadConfig())

	input := &secretsmanager.GetSecretValueInput{
		SecretId:     aws.String(secretName),
		VersionStage: aws.String("AWSCURRENT"), // VersionStage defaults to AWSCURRENT if unspecified
	}

	result, err := svc.GetSecretValue(context.TODO(), input)
	if err != nil {
		// For a list of exceptions thrown, see
		// https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
		log.Fatal(err.Error())
	}

	// Decrypts secret using the associated KMS key.
	return *result.SecretString

}

// Get API cursor from ParameterStore. Could be refactored to take an endpoint as 
// an argument and fetch the corresponding cursor.
func getCursor() string {
	paramInput := ssm.GetParameterInput{
		Name: aws.String(parameterName),
	}
	paramStore := ssm.NewFromConfig(loadConfig())
	output, err := paramStore.GetParameter(context.TODO(), &paramInput)
	if err != nil {
		log.Print(err)
		return ""
	}

	return *output.Parameter.Value
}

// Writes new cursor to parameter store. Could be refactored to take an endpoint as 
// an argument and fetch the corresponding cursor.
func setCursor(cursor string) {
	paramInput := ssm.PutParameterInput{
		Name:      aws.String(parameterName),
		Value:     &cursor,
		Overwrite: aws.Bool(true),
	}
	paramStore := ssm.NewFromConfig(loadConfig())

	paramStore.PutParameter(context.TODO(), &paramInput)
}

// Write logs to destination. In this case CloudWatch, but would require refactoring
// for your specific implementation and destination. 
func writeLogs(logItems []Item) {
	// Create a CloudWatchLogs client with additional configuration
	svc := cloudwatchlogs.NewFromConfig(loadConfig())

	// Each array of InputLogEvent's needs to be within a 24-hour window
	// In theory, this is only an issue on first call
	var events []types.InputLogEvent
	for _, item := range logItems {
		timestamp := item.Timestamp.UnixMilli()
		itemByte, _ := json.Marshal(item)
		itemString := string(itemByte)
		event := types.InputLogEvent{
			Message:   &itemString,
			Timestamp: &timestamp,
		}

		events = append(events, event)
	}

	logEvent := cloudwatchlogs.PutLogEventsInput{
		LogEvents:     events,
		LogGroupName:  &cloudwatchLogGroup,
		LogStreamName: &cloudwatchStream,
	}

	_, err := svc.PutLogEvents(context.TODO(), &logEvent)

	// log.Println("writeLogs error:")
	log.Println(err)
}
