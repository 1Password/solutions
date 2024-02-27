# 1Password Events API Base Golang Lambda Script

This folder contains the necessary components for getting starting piping events from the 1Password Event API into Cloudwatch Logs using a Lambda. If you like the region and the names of variables, you can use the AWS UI to create a few things and then upload bootstrap.zip as is.

If you need to make changes to the region or other parts of the script, you will need to recompile the script. See "[Build From Code](#build-from-code)" for guidance on recompiling. 

## Resources

[Events API Documentation](https://developer.1password.com/docs/events-api/)

## Using as-is

1. Setup the Events Reporting integration in 1Password using [these instructions](https://support.1password.com/events-reporting/#step-1-set-up-an-events-reporting-integration) and selecting `Other`. The only event types in the current script are Sign-In events.
2. Log into the us-east-1 region in AWS and create the following:
   - In AWS Secrets Manager, create a secret called `op-events-api-token`
     - Secret Type: Other type of secret
     - Key/value pairs: Plaintext -> paste in the bearer token
     - Everything else can be left as default
   - In AWS Systems Manager -> Parameter Store, create a secret called `op-events-api-cursor`
     - Tier: Standard
     - Type: String
     - Data Type: text
     - Value: first_run
   - In AWS CloudWatch, create a log group called `op-events-api-signins`, leaving everything else as default. Add a log stream to this log group call `op-events-api-signins-stream`
   - In AWS Lambda, create a new function called `op-events-api-signins-lambda`
     - Runtime: Amazon Linux 2
     - Architecture: arm64
     - Create a new role with basic Lambda permissions
3. After the lambda is created, go to AWS IAM -> Roles and click on `op-events-api-signins-lambda-role-#####` (###### just represents some random characters) and edit the json under the policy `AWSLambdaBasicExecutionRole-#####` to be:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue",
        "ssm:GetParameter",
        "ssm:PutParameter"
      ],
      "Resource": "arn:aws:logs:us-east-1:<account>:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue",
        "ssm:GetParameter",
        "ssm:PutParameter"
      ],
      "Resource": [
        "arn:aws:logs:us-east-1:<account>:log-group:/aws/lambda/op-events-api-signins-lambda:*"
      ]
    }
  ]
}
```

and then Add permissions -> attach policies, then add the policies `AmazonSSMFullAccess` and `SecretsManagerReadWrite`  
4. Return to the lambda function and on the right, select Upload from -> zip file and then navigate to and find bootstrap.zip from this folder.  
5. Navigate to test and then click the orange `Test` button, and you should get a success, and when you check the cloudwatch group and stream, there should be a new entry.  
6. Add a trigger for how frequently you would like this to run. For example, EventBridge, new rule with expression `rate(10 minutes)`

## Notes

- This is very much still in beta and has not been tested extensively
- This is not optimized yet - it's a first pass to get it working, there are definitely smarter ways to do this
- This starts with the last 24 hours of data, and does not currently load any events before then


## Build from code
If you need to make changes to the script to fit your environment or specifications, you will need to recompile the script. Once you've made your changes, use the following command to compile. Once compiled, you may follow the [deployment directions](#using-as-is), using the newly-compiled boostrap.zip. 

```bash
GOOS=linux GOARCH=arm64 go build -tags lambda.norpc -o bootstrap main.go && zip bootstrap.zip bootstrap
```
