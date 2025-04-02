# JS SDK Example: Computer Inventory Tracker

- [Demo video](https://1password.zoom.us/clips/share/WiuWv5kPSEa0DyiRYNymGw)

## Building locally:
1. Create a 1Password Service Account and add the secret reference to that token to the .env.template file and remove the .template suffix. 
2. Add the UUID of a vault the Service Account has read and write permissions on to the .env file. This is where 1Password items managed by the app will be stored. 
3. Build the image and deploy the container with `op run --env-file=.env -- docker compose up --build`
4. Visit the webapp in your browser on port 3000 (e.g., `localhost:3000`)