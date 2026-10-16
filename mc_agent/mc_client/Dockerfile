# MC-Agent 无头客户端（Mineflayer）
# 内存限制由 docker run --memory=1536m 强制；Node 堆限制 1024MB
FROM node:22-bookworm-slim

WORKDIR /app

# 国内镜像加速（部署环境网络受限）
RUN npm config set registry https://registry.npmmirror.com

COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force

COPY bot.js ./

ENV NODE_ENV=production
# Node 堆上限 1024MB（容器 1.5GB 内留出系统开销）
ENTRYPOINT ["node", "--max-old-space-size=1024", "bot.js"]
