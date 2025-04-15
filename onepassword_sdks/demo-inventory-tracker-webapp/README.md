# JS SDK Example: Computer Inventory Tracker

## Prerequisites
* [Docker Engine](https://docs.docker.com/get-started/get-docker/)
* [1Password CLI](https://developer.1password.com/docs/cli/get-started)
* A [1Password Service Account](https://my.1password.com/developer-tools/infrastructure-secrets/serviceaccount/) with read and write permissions in at least one vault.
* Learn about [secret references](https://developer.1password.com/docs/cli/secret-reference-syntax/)

## Deploy the Web App
1. Create a [1Password Service Account](https://developer.1password.com/docs/service-accounts) and add the [secret reference](https://developer.1password.com/docs/cli/secret-reference-syntax/) to that token to the .env.template file and remove the .template suffix. 
2. Add the UUID of a vault the Service Account has read and write permissions on to the .env file. This is where 1Password items managed by the app will be stored. 
3. Build the image and deploy the container with `op run --env-file=.env -- docker compose up --build`
4. Visit the webapp in your browser on port 3000 (e.g., `localhost:3000`)