/**
 * MC-Agent 无头 Minecraft 客户端（Mineflayer）
 *
 * 环境变量:
 *   MC_SERVER      MC 服务器地址
 *   MC_PORT        MC 服务器端口（默认 25565）
 *   BOT_NAME       游戏昵称
 *   BOT_HTTP_PORT  本进程 HTTP 控制端口（默认 31889）
 *   PLUGIN_HTTP    插件事件接收地址（如 http://127.0.0.1:31888）
 *   CONTAINER_NAME 容器名（事件上报用）
 *   MC_OFFLINE     离线认证模式（true/false）
 *
 * 控制接口: POST /cmd  {"id","cmd","args"}  ->  {"id","ok","result"}
 * 事件上报: POST {PLUGIN_HTTP}/event  {"type","container","data"}
 */
const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals: { GoalNear, GoalBlock, GoalXZ, GoalFollow } } = require('mineflayer-pathfinder')
const collectBlock = require('mineflayer-collectblock').plugin
const armorManager = require('mineflayer-armor-manager')
const http = require('http')

// ================= 配置 =================
const CFG = {
  server: process.env.MC_SERVER || '127.0.0.1',
  port: parseInt(process.env.MC_PORT || '25565', 10),
  name: process.env.BOT_NAME || 'MaiBotPlayer',
  httpPort: parseInt(process.env.BOT_HTTP_PORT || '31889', 10),
  pluginHttp: process.env.PLUGIN_HTTP || 'http://127.0.0.1:31888',
  container: process.env.CONTAINER_NAME || process.env.HOSTNAME || 'unknown',
  offline: (process.env.MC_OFFLINE || 'true').toLowerCase() === 'true',
  maxReconnect: parseInt(process.env.MAX_RECONNECT || '5', 10),
}

const RARE_ITEMS = [
  'diamond', 'netherite', 'ancient_debris', 'elytra', 'totem_of_undying',
  'nether_star', 'beacon', 'enchanted_golden_apple', 'trident', 'shulker_shell',
  'heart_of_the_sea', 'music_disc',
]
const FOODS = new Set([
  'cooked_beef', 'cooked_porkchop', 'cooked_mutton', 'cooked_chicken', 'cooked_rabbit',
  'cooked_cod', 'cooked_salmon', 'bread', 'baked_potato', 'pumpkin_pie', 'apple',
  'golden_apple', 'enchanted_golden_apple', 'beef', 'porkchop', 'mutton', 'chicken',
  'rabbit', 'cod', 'salmon', 'carrot', 'potato', 'beetroot', 'sweet_berries',
  'glow_berries', 'melon_slice', 'cookie', 'rabbit_stew', 'mushroom_stew',
  'suspicious_stew', 'dried_kelp', 'honey_bottle',
])
const HOSTILE_MOBS = [
  'zombie', 'skeleton', 'creeper', 'spider', 'witch', 'enderman', 'drowned',
  'husk', 'stray', 'phantom', 'pillager', 'vindicator', 'vex', 'ravager',
  'piglin', 'hoglin', 'zombified_piglin', 'blaze', 'wither_skeleton', 'slime',
  'magma_cube', 'silverfish', 'guardian', 'elder_guardian', 'pillager',
]

// ================= 状态 =================
let bot = null
let reconnectAttempts = 0
let joinedOnce = false
let lastHealthEvent = 0
let lastFood = 20
let invSnapshot = new Map()
let followTarget = null
let busy = null // 当前长任务 Promise
const startedAt = Date.now()

// ================= 事件上报 =================
function postEvent(type, data) {
  const payload = JSON.stringify({ type, container: CFG.container, data: data || {} })
  try {
    const url = new URL(CFG.pluginHttp + '/event')
    const req = http.request(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, timeout: 5000 }, res => { res.resume() })
    req.on('error', () => {})
    req.on('timeout', () => req.destroy())
    req.end(payload)
  } catch (e) { /* ignore */ }
}
const log = (...a) => console.log(new Date().toISOString(), ...a)

// ================= 机器人生命周期 =================
function createBot() {
  bot = mineflayer.createBot({
    host: CFG.server,
    port: CFG.port,
    username: CFG.name,
    auth: CFG.offline ? 'offline' : 'microsoft',
    version: false,
    respawn: true,
  })

  bot.loadPlugin(pathfinder)
  bot.loadPlugin(collectBlock)
  bot.loadPlugin(armorManager)

  bot.once('spawn', () => {
    log('spawned on', CFG.server)
    reconnectAttempts = 0
    snapshotInventory()
    const first = !joinedOnce
    joinedOnce = true
    postEvent(first ? 'join' : 'spawn', { username: CFG.name, first })
    const mcData = require('minecraft-data')(bot.version)
    bot.movements = new Movements(bot, mcData)
    bot.pathfinder.setMovements(bot.movements)
  })

  bot.on('message', (jsonMsg) => {
    const text = jsonMsg.toString ? jsonMsg.toString() : String(jsonMsg)
    if (text && text.length < 300) log('server:', text)
  })

  bot.on('chat', (username, message) => {
    if (username === bot.username) return
    if (!username || username === 'Server') return
    postEvent('chat', { player: username, message: String(message).slice(0, 200) })
  })

  bot.on('death', () => {
    postEvent('death', { cause: lastDamageCause || '未知原因' })
    followTarget = null
    setTimeout(() => { try { bot.respawn() } catch (e) {} }, 1000)
  })

  bot.on('health', () => {
    const hp = Math.ceil(bot.health)
    if (hp <= (parseInt(process.env.HEALTH_LOW || '8', 10)) && Date.now() - lastHealthEvent > 30000) {
      lastHealthEvent = Date.now()
      postEvent('health_low', { hp, max_hp: 20, food: Math.ceil(bot.food) })
    }
  })

  let lastDamageCause = '未知原因'
  bot._client.on('damage_event', (p) => {
    try {
      if (p && p.type) lastDamageCause = String(p.type)
      else if (p && p.entityId != null) {
        const src = bot.entities[p.entityId]
        if (src) lastDamageCause = src.type === 'player' ? `被玩家 ${src.username} 攻击` : `被 ${src.name || '生物'} 攻击`
      }
    } catch (e) {}
  })

  bot.on('kicked', (reason) => {
    log('kicked:', reason)
    followTarget = null
    postEvent('kicked', { reason: String(reason).slice(0, 500) })
    scheduleReconnect()
  })

  bot.on('error', (err) => {
    log('error:', err.message)
    postEvent('error', { message: String(err.message).slice(0, 300) })
  })

  bot.on('end', () => {
    followTarget = null
    if (!reconnecting) {
      log('connection ended')
      scheduleReconnect()
    }
  })

  // 周期任务
  if (!global.__timers) {
    global.__timers = true
    setInterval(() => { if (bot && bot.entity) snapshotAndDiff() }, 3000)
    setInterval(() => { if (bot && bot.entity) sendTick() }, 60000)
    setInterval(() => { if (bot && bot.entity) autoSurvive() }, 10000)
  }
}

let reconnecting = false
let reconnectTimer = null
function scheduleReconnect() {
  if (reconnectAttempts >= CFG.maxReconnect) {
    postEvent('exit', { reason: '重连次数耗尽', reconnect_exhausted: true, attempts: reconnectAttempts })
    log('reconnect exhausted, exiting')
    process.exit(1) // 交给 docker restart 策略
  }
  reconnecting = true
  reconnectAttempts++
  const delay = Math.min(15000, 3000 * reconnectAttempts)
  log(`reconnect attempt ${reconnectAttempts}/${CFG.maxReconnect} in ${delay}ms`)
  postEvent('error', { message: `连接断开，${delay / 1000}s 后第 ${reconnectAttempts} 次重连` })
  clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    reconnecting = false
    try { if (bot) bot.end() } catch (e) {}
    createBot()
  }, delay)
}

// ================= 生存辅助 =================
function autoSurvive() {
  try {
    if (!bot || !bot.entity) return
    if (busy) return
    const food = Math.ceil(bot.food)
    if ((food < 16 || bot.health < 10) && food < 20) {
      eatBestFood(true)
    }
    if (bot.health < 14) equipBestArmor(true)
  } catch (e) {}
}

function foodItems() {
  return bot.inventory.items().filter(it => FOODS.has(it.name))
}

async function eatBestFood(silent) {
  const foods = foodItems().sort((a, b) => (b.metadata || 0) - (a.metadata || 0))
  if (!foods.length) {
    if (!silent) return { ok: false, result: '背包里没有食物' }
    return
  }
  await bot.equip(foods[0], 'hand')
  await bot.consume()
  lastFood = Math.ceil(bot.food)
  if (!silent) return { ok: true, result: `吃了 ${foods[0].name}` }
}

async function equipBestArmor(silent) {
  try { bot.armorManager.equipAll(); if (!silent) return { ok: true, result: '已穿戴最好的装备' } } catch (e) {
    if (!silent) return { ok: false, result: '穿戴失败: ' + e.message }
  }
}

function snapshotInventory() {
  invSnapshot = new Map()
  for (const it of bot.inventory.items()) invSnapshot.set(it.name, (invSnapshot.get(it.name) || 0) + it.count)
}

function snapshotAndDiff() {
  const now = new Map()
  for (const it of bot.inventory.items()) now.set(it.name, (now.get(it.name) || 0) + it.count)
  for (const [name, count] of now) {
    const old = invSnapshot.get(name) || 0
    if (count > old && RARE_ITEMS.some(r => name.includes(r))) {
      postEvent('rare_item', { item: name, count: count - old })
    }
  }
  invSnapshot = now
}

function sendTick() {
  const st = statusPayload()
  if (st) postEvent('tick', st)
}

function statusPayload() {
  if (!bot || !bot.entity) return null
  const p = bot.entity.position
  const timeOfDay = bot.time ? (bot.time.timeOfDay % 24000) : 0
  const isNight = timeOfDay > 13000 && timeOfDay < 23000
  const nearby = {}
  for (const e of Object.values(bot.entities)) {
    if (e.id === bot.entity.id) continue
    if (e.position.distanceTo(bot.entity.position) > 16) continue
    const kind = e.type === 'player' ? 'player:' + e.username : (e.name || 'unknown')
    if (e.type === 'player' || HOSTILE_MOBS.some(m => (e.name || '').includes(m))) {
      nearby[kind] = (nearby[kind] || 0) + 1
    }
  }
  const inv = {}
  for (const it of bot.inventory.items()) inv[it.name] = (inv[it.name] || 0) + it.count
  const invSummary = Object.entries(inv).sort((a, b) => b[1] - a[1]).slice(0, 8)
    .map(([n, c]) => `${n}x${c}`).join(', ')
  const held = bot.heldItem ? bot.heldItem.name : '空手'
  return {
    pos: { x: Math.round(p.x), y: Math.round(p.y), z: Math.round(p.z) },
    hp: Math.ceil(bot.health), food: Math.ceil(bot.food),
    held_item: held, time_of_day: Math.round(timeOfDay), is_night: isNight,
    dimension: bot.game ? bot.game.dimension : '',
    nearby_entities: Object.keys(nearby).length ? JSON.stringify(nearby) : '无威胁',
    inventory_summary: invSummary || '空',
  }
}

// ================= 命令实现 =================
function markBusy(promise) {
  busy = promise.finally(() => { busy = null })
  return promise
}

async function cmdStatus() {
  const st = statusPayload()
  return st ? { ok: true, result: JSON.stringify(st) } : { ok: false, result: '未连接' }
}

async function cmdSay(args) {
  const msg = String(args.message || '').slice(0, 240)
  if (!msg) return { ok: false, result: '消息为空' }
  bot.chat(msg)
  return { ok: true, result: `已说: ${msg}` }
}

async function cmdGoto(args) {
  const x = Number(args.x), y = Number(args.y), z = Number(args.z)
  if ([x, y, z].some(Number.isNaN)) return { ok: false, result: '坐标参数无效' }
  const range = Number.isFinite(Number(args.range)) ? Number(args.range) : 2
  await markBusy(bot.pathfinder.goto(new GoalNear(x, y, z, range)))
  return { ok: true, result: `已到达 ${x},${y},${z} 附近` }
}

async function cmdCome(args) {
  const name = args.player || CFG.name
  const target = playerByName(name)
  if (!target) return { ok: false, result: `找不到玩家 ${name}` }
  const range = Number.isFinite(Number(args.range)) ? Number(args.range) : 2
  await markBusy(bot.pathfinder.goto(new GoalNear(target.position.x, target.position.y, target.position.z, range)))
  return { ok: true, result: `已到 ${target.username} 身边` }
}

async function cmdFollow(args) {
  const name = args.player || CFG.name
  const target = playerByName(name)
  if (!target) return { ok: false, result: `找不到玩家 ${name}` }
  followTarget = target
  bot.pathfinder.setGoal(new GoalFollow(target, 3), true)
  return { ok: true, result: `开始跟随 ${target.username}` }
}

function cmdUnfollow() {
  followTarget = null
  bot.pathfinder.stop()
  return Promise.resolve({ ok: true, result: '停止跟随' })
}

async function cmdCollect(args) {
  const blockName = String(args.block || '').toLowerCase()
  let count = Math.min(parseInt(args.count || '1', 10) || 1, 16)
  const mcData = require('minecraft-data')(bot.version)
  const candidates = [
    blockName,
    blockName.endsWith('_ore') ? blockName : blockName + '_ore',
    'log', blockName === 'wood' || blockName === 'log' ? 'log' : blockName,
  ].filter(Boolean)
  let blockType = null
  for (const c of candidates) {
    try { blockType = mcData.blocksByName[c]; if (blockType) break } catch (e) {}
    blockType = mcData.blocksByName[c] || null
    if (blockType) break
  }
  if (!blockType) {
    // 常见别名
    const alias = { '钻石矿': 'diamond_ore', '木头': 'log', '树': 'log', '石头': 'stone', '圆石': 'cobblestone', '煤矿': 'coal_ore', '铁矿': 'iron_ore' }
    blockType = mcData.blocksByName[alias[blockName]] || null
  }
  if (!blockType) return { ok: false, result: `未知方块: ${blockName}` }
  const blocks = bot.findBlocks({ matching: blockType, maxDistance: 64, count })
  if (!blocks.length) return { ok: false, result: `附近 64 格内没有 ${blockType.name}` }
  await markBusy(bot.collectBlock.collect(blocks))
  return { ok: true, result: `采集了 ${blocks.length} 个 ${blockType.name}` }
}

async function cmdDig(args) {
  let target = null
  if ([args.x, args.y, args.z].every(v => v !== undefined && !Number.isNaN(Number(v)))) {
    const b = bot.blockAt(new (require('vec3').Vec3)(Number(args.x), Number(args.y), Number(args.z)))
    if (!b || b.boundingBox === 'empty') return { ok: false, result: '该坐标没有可挖方块' }
    target = b
  } else {
    target = bot.blockAt(bot.entity.position.offset(0, -1, 0))
  }
  if (!target) return { ok: false, result: '找不到目标方块' }
  await markBusy(bot.dig(target))
  return { ok: true, result: `挖掉了 ${target.name}` }
}

async function cmdCraft(args) {
  let item = String(args.item || '').toLowerCase().trim()
  const count = Math.min(parseInt(args.count || '1', 10) || 1, 64)
  const alias = { '工作台': 'crafting_table', '镐': 'wooden_pickaxe', '木镐': 'wooden_pickaxe', '石镐': 'stone_pickaxe', '火把': 'torch', '熔炉': 'furnace' }
  item = alias[item] || item
  const mcData = require('minecraft-data')(bot.version)
  const itemObj = mcData.itemsByName[item] || mcData.blocksByName[item]
  if (!itemObj) return { ok: false, result: `未知物品: ${item}` }
  let recipes = bot.recipesFor(itemObj.id, null, 1, null)
  if (!recipes.length) return { ok: false, result: `无法合成 ${item}（缺少配方或材料）` }
  const needsTable = recipes.some(r => r.requiresTable)
  let table = null
  if (needsTable) {
    table = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 32 })
    if (!table) {
      // 尝试先合成工作台
      const ctRecipes = bot.recipesFor(mcData.blocksByName.crafting_table.id, null, 1, null)
      if (ctRecipes.length) {
        await markBusy(bot.craft(ctRecipes[0], 1))
        table = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 32 })
      }
    }
    if (!table) return { ok: false, result: '需要工作台但附近没有（也无法合成）' }
  }
  const usable = bot.recipesFor(itemObj.id, null, 1, table)
  if (!usable.length) return { ok: false, result: `材料不足，无法合成 ${item}` }
  await markBusy(bot.craft(usable[0], count, table))
  return { ok: true, result: `合成了 ${count} 个 ${item}` }
}

async function cmdAttack(args) {
  const targetName = String(args.target || '').toLowerCase()
  const radius = Math.min(Number(args.radius) || 8, 16)
  let entity = null
  for (const e of Object.values(bot.entities)) {
    if (e.id === bot.entity.id) continue
    const dist = e.position.distanceTo(bot.entity.position)
    if (dist > radius) continue
    if (e.type === 'player' && e.username && e.username.toLowerCase().includes(targetName)) { entity = e; break }
    if (e.name && e.name.toLowerCase().includes(targetName)) { entity = e; break }
  }
  if (!entity && !targetName) {
    // 攻击最近敌对生物
    let best = Infinity
    for (const e of Object.values(bot.entities)) {
      if (e.id === bot.entity.id || e.type === 'player') continue
      if (!HOSTILE_MOBS.some(m => (e.name || '').includes(m))) continue
      const d = e.position.distanceTo(bot.entity.position)
      if (d < best && d <= radius) { best = d; entity = e }
    }
  }
  if (!entity) return { ok: false, result: `范围内没找到目标 ${targetName || '(敌对生物)'}` }
  const label = entity.type === 'player' ? entity.username : entity.name
  const deadline = Date.now() + 8000
  while (Date.now() < deadline) {
    if (entity.isValid === false) break
    await bot.lookAt(entity.position.offset(0, entity.height || 1, 0))
    bot.attack(entity)
    await new Promise(r => setTimeout(r, 600))
    if (entity.position.distanceTo(bot.entity.position) > radius + 4) break
  }
  return { ok: true, result: `攻击了 ${label}` }
}

async function cmdEat() {
  const r = await eatBestFood(false)
  return r || { ok: false, result: '背包里没有食物' }
}

async function cmdEquipBest() {
  const r = await equipBestArmor(false)
  return r || { ok: true, result: '已穿戴最好的装备' }
}

function cmdListInventory() {
  const inv = {}
  for (const it of bot.inventory.items()) inv[it.name] = (inv[it.name] || 0) + it.count
  const summary = Object.entries(inv).map(([n, c]) => `${n}x${c}`).join(', ') || '空'
  return Promise.resolve({ ok: true, result: summary })
}

async function cmdDrop(args) {
  const name = String(args.item || '')
  const count = parseInt(args.count || '1', 10) || 1
  const item = bot.inventory.items().find(it => it.name.includes(name))
  if (!item) return { ok: false, result: `背包里没有 ${name}` }
  await bot.tossStack(item)
  return { ok: true, result: `丢弃了 ${item.name}x${item.count}` }
}

async function cmdLook(args) {
  const target = playerByName(args.player || CFG.name)
  if (!target) return { ok: false, result: `找不到玩家 ${args.player}` }
  await bot.lookAt(target.position.offset(0, target.height || 1.6, 0))
  return { ok: true, result: `看向 ${target.username}` }
}

function cmdStop() {
  followTarget = null
  bot.pathfinder.stop()
  bot.stopDigging()
  return Promise.resolve({ ok: true, result: '已停止所有动作' })
}

function playerByName(name) {
  const lower = String(name || '').toLowerCase()
  if (!lower) return null
  if (lower === bot.username.toLowerCase()) return bot.entity
  for (const e of Object.values(bot.entities)) {
    if (e.type === 'player' && e.username && e.username.toLowerCase().includes(lower)) return e
  }
  return null
}

// ================= HTTP 控制服务 =================
const COMMANDS = {
  status: cmdStatus,
  say: cmdSay,
  goto: cmdGoto,
  come: cmdCome,
  follow: cmdFollow,
  unfollow: cmdUnfollow,
  collect: cmdCollect,
  dig: cmdDig,
  craft: cmdCraft,
  attack: cmdAttack,
  eat: cmdEat,
  equip_best: cmdEquipBest,
  list_inventory: cmdListInventory,
  drop: cmdDrop,
  look: cmdLook,
  stop: cmdStop,
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ ok: true, bot: !!bot, connected: !!(bot && bot.entity) }))
    return
  }
  if (req.method !== 'POST' || req.url !== '/cmd') {
    res.writeHead(404); res.end('{"error":"not found"}'); return
  }
  let body = ''
  req.on('data', c => { body += c; if (body.length > 1e6) req.destroy() })
  req.on('end', async () => {
    let id = '', ok = false, result = '未知命令'
    try {
      const payload = JSON.parse(body || '{}')
      id = payload.id || ''
      const cmd = String(payload.cmd || '')
      const args = payload.args || {}
      if (!bot || !bot.entity) {
        result = '机器人未连接到服务器'
      } else if (COMMANDS[cmd]) {
        try {
          const r = await Promise.race([
            COMMANDS[cmd](args),
            new Promise((_, rej) => setTimeout(() => rej(new Error('动作执行超时')), 110000)),
          ])
          ok = !!(r && r.ok)
          result = (r && r.result) || '完成'
        } catch (e) {
          ok = false
          result = '执行失败: ' + (e && e.message ? e.message : e)
          try { bot.pathfinder.stop() } catch (_) {}
        }
      }
    } catch (e) {
      ok = false; result = 'bad request: ' + e.message
    }
    res.writeHead(ok ? 200 : 200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ id, ok, result }))
    log(`cmd done ok=${ok}:`, result)
  })
})

server.listen(CFG.httpPort, '0.0.0.0', () => log(`control server on :${CFG.httpPort}`))

// 进程级兜底
process.on('unhandledRejection', (e) => log('unhandledRejection:', e && e.message))
process.on('uncaughtException', (e) => {
  log('uncaughtException:', e && e.message)
  postEvent('error', { message: '进程异常: ' + (e && e.message) })
})

createBot()
