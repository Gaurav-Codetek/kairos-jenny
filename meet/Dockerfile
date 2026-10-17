# Jenny's body for Google Meet: Node + Playwright's Chromium, run headful on a virtual display (Meet is less likely to
# refuse a real browser window than a headless one).
FROM mcr.microsoft.com/playwright:v1.47.2-jammy

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends x11vnc novnc websockify && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund && npx playwright install --with-deps chrome
COPY src ./src
COPY test ./test

ENV PORT=7070
EXPOSE 7070 6080
CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1280x1024x24", "node", "src/server.js"]
