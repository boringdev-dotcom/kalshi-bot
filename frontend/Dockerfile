# Courtside UI: build the static app, serve it with nginx, and proxy /api and
# /ws to the API service so the browser sees one origin (the login cookie
# depends on that).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# The nginx image renders *.template files with environment variables at start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Where the API lives. Override both in the host's environment if it moves.
ENV BACKEND_URL=https://kalshi-bot-j796.onrender.com
ENV BACKEND_HOST=kalshi-bot-j796.onrender.com

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
