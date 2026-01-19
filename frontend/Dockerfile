# Build stage
FROM node:22-alpine AS build

WORKDIR /app

# Build arguments for environment variables (required at build time)
ARG VITE_API_URL
ARG VITE_ODDS_API_KEY

ENV VITE_API_URL=$VITE_API_URL
ENV VITE_ODDS_API_KEY=$VITE_ODDS_API_KEY

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the app (environment variables are embedded at build time)
RUN npm run build

# Production stage - serve with nginx
FROM nginx:alpine

# Copy built files to nginx
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx config for SPA routing + WebSocket proxy
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
