# syntax=docker/dockerfile:1

# Newest stable 1Password CLI by default. Set a version number to pin one.
ARG OP_VERSION=latest

FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS deps
WORKDIR /webapp
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
RUN mkdir logs

FROM alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8 AS op-cli
ARG OP_VERSION
ARG TARGETARCH
# Fingerprint of 1Password's public release signing key. It's public, but Docker's
# linter flags any ARG named *KEY*, hence the name.
ARG OP_SIGNER_FINGERPRINT=3FEF9748469ADBE15DA7CA80AC2D62742012EA22
RUN apk add --no-cache curl gnupg unzip
WORKDIR /tmp/op
# Fetched fresh on every build, so a new CLI release isn't stuck behind the build cache.
ADD https://app-updates.agilebits.com/check/1/0/CLI2/en/2.0.0/N latest.json
RUN version="${OP_VERSION}" \
 && if [ "$version" = "latest" ]; then version="$(sed -n 's/.*"version":"\([^"]*\)".*/\1/p' latest.json)"; fi \
 && echo "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "Could not determine the 1Password CLI version (got '$version')" >&2; exit 1; } \
 && echo "Installing 1Password CLI $version" \
 && curl -fsSLo op.zip "https://cache.agilebits.com/dist/1P/op2/pkg/v${version}/op_linux_${TARGETARCH}_v${version}.zip" \
 && unzip -q op.zip op op.sig \
 && curl -fsSL https://downloads.1password.com/linux/keys/1password.asc | gpg --batch --import \
 && gpg --batch --status-fd 1 --verify op.sig op | grep -q "VALIDSIG ${OP_SIGNER_FINGERPRINT}" \
 && ./op --version

FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1

# Remove npm, the package manager and the shell. The app doesn't need them.
# The CA certificates are kept because op needs them.
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
           /opt/yarn-* /usr/local/bin/yarn /usr/local/bin/yarnpkg /usr/local/bin/docker-entrypoint.sh \
 && echo ca-certificates-bundle >> /etc/apk/world \
 && apk del --no-cache --purge apk-tools
# busybox can't remove itself cleanly, so node does it.
RUN ["node", "-e", "const fs = require('fs'); const path = require('path'); for (const dir of ['/bin', '/sbin', '/usr/bin', '/usr/sbin']) { for (const name of fs.readdirSync(dir)) { const p = path.join(dir, name); try { if (fs.readlinkSync(p).includes('busybox')) fs.unlinkSync(p); } catch {} } } fs.unlinkSync('/bin/busybox');"]

WORKDIR /webapp
COPY --from=op-cli /tmp/op/op /usr/local/bin/op
COPY --from=deps /webapp/node_modules ./node_modules
COPY --from=deps --chown=node:node /webapp/logs ./logs
COPY package.json webapp.js rate-limits.js ./
COPY views ./views
COPY public ./public

# Listen on all interfaces inside the container. Compose only exposes it to this machine.
ENV HOST=0.0.0.0 \
    PORT=3001 \
    NODE_ENV=production
EXPOSE 3001

USER node
# The base image's entrypoint is a shell script, and there's no shell anymore.
ENTRYPOINT []
CMD ["node", "webapp.js"]
