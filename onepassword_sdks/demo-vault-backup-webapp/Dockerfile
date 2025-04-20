# Use Node.js 18 as the base image for the container
FROM node:20

# Set the working directory to /app inside the container
WORKDIR /webapp

# Install required tools and configure the 1Password CLI repository
RUN apt-get update && \
    apt-get install -y \
    curl \
    gnupg \
    python3 \
    python3-pip \
    ca-certificates \
    lsb-release \
    docker.io && \
    curl -L "https://github.com/docker/compose/releases/download/v2.20.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && \
    chmod +x /usr/local/bin/docker-compose && \
    curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
    gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" | \
    tee /etc/apt/sources.list.d/1password.list && \
    mkdir -p /etc/debsig/policies/AC2D62742012EA22/ && \
    curl -sS https://downloads.1password.com/linux/debian/debsig/1password.pol | \
    tee /etc/debsig/policies/AC2D62742012EA22/1password.pol && \
    mkdir -p /usr/share/debsig/keyrings/AC2D62742012EA22 && \
    curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
    gpg --dearmor --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg && \
    apt-get update && \
    apt-get install -y 1password-cli

# Check the installed version of 1Password CLI to ensure it’s working
RUN op --version

# Verify Python 3 is installed correctly
RUN python3 --version

# Confirm Docker CLI is installed and functional
RUN docker --version

# Verify Docker Compose installation
RUN docker-compose --version

# Copy package.json and package-lock.json (if present) to the working directory
COPY package*.json ./

# Install Node.js dependencies defined in package.json
RUN npm install

# Copy all remaining application files to the container
COPY . .

# Set permissions: 755 for directories, 644 for files
RUN chown -R node:node /webapp && \
    find /webapp -type d -exec chmod 755 {} \; && \
    find /webapp -type f -exec chmod 644 {} \;

# Switch to non-root user
USER node

# Expose port 3002 for the application to listen on
EXPOSE 3002

# Define the command to start the Node.js application
CMD ["npm", "webapp.js"]
