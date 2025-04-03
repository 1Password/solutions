# JS SDK Example: Computer Inventory Tracker

## Prerequisites
* Docker installed and running ([Docker Documentation](https://docs.docker.com/get-started/get-docker/))
* 1Password CLI installed and linked to a 1Password account ([Get Started with 1Password CLI](https://developer.1password.com/docs/cli/get-started))
* A 1Password Service Account with Read/Write access to at least one vault ([Get Started with Service Accounts](https://developer.1password.com/docs/service-accounts))
* Learn about [Secret References](https://developer.1password.com/docs/cli/secret-reference-syntax/)

## Deploy the Web App
1. Create a [1Password Service Account](https://developer.1password.com/docs/service-accounts) and add the [secret reference](https://developer.1password.com/docs/cli/secret-reference-syntax/) to that token to the .env.template file and remove the .template suffix. 
2. Add the UUID of a vault the Service Account has read and write permissions on to the .env file. This is where 1Password items managed by the app will be stored. 
3. Build the image and deploy the container with `op run --env-file=.env -- docker compose up --build`
4. Visit the webapp in your browser on port 3000 (e.g., `localhost:3000`)