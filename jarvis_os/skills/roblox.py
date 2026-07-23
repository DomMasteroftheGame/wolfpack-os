"""Roblox game development skill.

Scaffolds Roblox Studio projects with starter scripts, RemoteEvents, and common
Luau patterns. Roblox Studio is required to open .rbxl files; this skill creates
the project folder and Lua scripts that can be pasted into Studio.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_ROBLOX_DIR = Path(__file__).parent.parent.parent / "games" / "roblox"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_project_dir(project_dir: str | None, default: Path) -> Path:
    if not project_dir:
        return default
    lowered = project_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(project_dir).expanduser()


class RobloxSkill(Skill):
    """Scaffold Roblox games with Luau scripts and Studio-ready structure."""

    name = "roblox"
    description = (
        "Create Roblox game projects with starter Luau scripts, common mechanics, "
        "and RemoteEvents. Outputs a folder that can be imported into Roblox Studio."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_project", "generate_script", "wave_survival"],
                "description": "Roblox action. 'wave_survival' scaffolds a complete wave-survival game (growing waves, chasing enemies, HUD, spectator, winner) in Script-Sync layout. Use 'theme' to pick the flavor.",
            },
            "theme": {
                "type": "string",
                "enum": ["scifi", "medieval"],
                "description": "wave_survival theme. 'scifi' (default) = laser gun vs exploding creatures. 'medieval' = sword vs an invading army of armored soldiers.",
            },
            "project_name": {
                "type": "string",
                "description": "Name of the Roblox game.",
            },
            "project_dir": {
                "type": "string",
                "description": "Directory for the project.",
            },
            "game_type": {
                "type": "string",
                "description": "Game genre, e.g. 'obby', 'tycoon', 'simulator', 'pvp'.",
            },
            "script_type": {
                "type": "string",
                "enum": ["leaderstats", "datastore", "currency", "shop", "shop_server", "teleport", "admin", "gamepass", "developer_product", "round", "checkpoints"],
                "description": "Type of Luau script to generate.",
            },
        },
        "required": ["action"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "create_project":
            return await self._create_project(kwargs)
        if action == "generate_script":
            return await self._generate_script(kwargs)
        if action == "wave_survival":
            return await self._wave_survival(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _create_project(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_name = kwargs.get("project_name", "MyRobloxGame")
        game_type = kwargs.get("game_type", "obby")
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_ROBLOX_DIR) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        (scripts_dir / "leaderstats.lua").write_text(
            """-- leaderstats.lua
-- Put this in ServerScriptService

local Players = game:GetService("Players")

Players.PlayerAdded:Connect(function(player)
    local stats = Instance.new("Folder")
    stats.Name = "leaderstats"
    stats.Parent = player

    local coins = Instance.new("IntValue")
    coins.Name = "Coins"
    coins.Value = 0
    coins.Parent = stats

    local level = Instance.new("IntValue")
    level.Name = "Level"
    level.Value = 1
    level.Parent = stats
end)
""",
            encoding="utf-8",
        )

        (scripts_dir / "datastore.lua").write_text(
            """-- datastore.lua  (ServerScriptService)
-- Persists each player's Coins/Level across sessions. Use this INSTEAD of the
-- plain leaderstats.lua when you want saving -- it sets up leaderstats too, so
-- don't run both (you'd get two leaderstats folders).
--
-- IMPORTANT: In Studio, turn on Game Settings > Security > "Enable Studio Access
-- to API Services" or DataStores silently fail. DataStores also need the game
-- published. Docs: https://create.roblox.com/docs/cloud-services/data-stores

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")

local playerStore = DataStoreService:GetDataStore("PlayerData_v1")
local DEFAULT = { Coins = 0, Level = 1, Stage = 1 }

-- Load returns the saved table, or nil if the network call FAILED (so we can
-- avoid overwriting good data with defaults later).
local function loadData(userId)
    local ok, result = pcall(function()
        return playerStore:GetAsync("Player_" .. userId)
    end)
    if ok then
        return result or table.clone(DEFAULT)
    end
    warn("DataStore load failed for " .. userId .. ": " .. tostring(result))
    return nil
end

local function saveData(userId, data)
    -- UpdateAsync is safer than SetAsync across multiple servers.
    local ok, err = pcall(function()
        playerStore:UpdateAsync("Player_" .. userId, function()
            return data
        end)
    end)
    if not ok then
        warn("DataStore save failed for " .. userId .. ": " .. tostring(err))
    end
end

Players.PlayerAdded:Connect(function(player)
    local data = loadData(player.UserId)
    if data == nil then
        data = table.clone(DEFAULT)
        player:SetAttribute("DataLoadFailed", true)  -- don't overwrite good data on save
    end
    player:SetAttribute("Stage", data.Stage or 1)  -- checkpoints.lua reads this

    local stats = Instance.new("Folder")
    stats.Name = "leaderstats"

    local coins = Instance.new("IntValue")
    coins.Name = "Coins"
    coins.Value = data.Coins or 0
    coins.Parent = stats

    local level = Instance.new("IntValue")
    level.Name = "Level"
    level.Value = data.Level or 1
    level.Parent = stats

    stats.Parent = player
end)

local function savePlayer(player)
    if player:GetAttribute("DataLoadFailed") then return end  -- their load errored; skip
    local stats = player:FindFirstChild("leaderstats")
    if not stats then return end
    local coins = stats:FindFirstChild("Coins")
    local level = stats:FindFirstChild("Level")
    if not coins or not level then return end
    saveData(player.UserId, {
        Coins = coins.Value,
        Level = level.Value,
        Stage = player:GetAttribute("Stage") or 1,
    })
end

Players.PlayerRemoving:Connect(savePlayer)

-- Save everyone when the server shuts down (BindToClose gets ~30s).
game:BindToClose(function()
    for _, player in ipairs(Players:GetPlayers()) do
        task.spawn(savePlayer, player)  -- run saves in parallel
    end
    task.wait(3)  -- let the async saves finish
end)
""",
            encoding="utf-8",
        )

        (scripts_dir / "checkpoints.lua").write_text(
            """-- checkpoints.lua  (ServerScriptService)
-- Obby spawns + checkpoints. Put SpawnLocation parts in a Folder named
-- "Checkpoints" in Workspace, named "1", "2", "3"... (1 = the start). Players
-- respawn at the highest checkpoint they've reached; the stage saves via
-- datastore.lua (it stores the "Stage" attribute).
-- Docs: https://create.roblox.com/docs/tutorials/curriculums/gameplay-scripting/spawn-respawn

local Players = game:GetService("Players")
local checkpoints = workspace:WaitForChild("Checkpoints")

local function spawnAtStage(player, char)
    local stage = player:GetAttribute("Stage") or 1
    local cp = checkpoints:FindFirstChild(tostring(stage))
    if cp then
        player.RespawnLocation = cp  -- future respawns land here
        local root = char:WaitForChild("HumanoidRootPart")
        root.CFrame = cp.CFrame + Vector3.new(0, 3, 0)  -- move them there now
    end
end

Players.PlayerAdded:Connect(function(player)
    if player:GetAttribute("Stage") == nil then
        player:SetAttribute("Stage", 1)
    end
    local stats = player:FindFirstChild("leaderstats") or player:WaitForChild("leaderstats", 5)
    if stats and not stats:FindFirstChild("Stage") then
        local stageVal = Instance.new("IntValue")
        stageVal.Name = "Stage"
        stageVal.Value = player:GetAttribute("Stage") or 1
        stageVal.Parent = stats
    end
    player.CharacterAdded:Connect(function(char)
        spawnAtStage(player, char)
    end)
end)

-- Touching a higher-numbered checkpoint advances the player's stage.
for _, cp in ipairs(checkpoints:GetChildren()) do
    local stageNum = tonumber(cp.Name)
    if stageNum then
        cp.Touched:Connect(function(hit)
            local player = Players:GetPlayerFromCharacter(hit.Parent)
            if not player then return end
            if stageNum > (player:GetAttribute("Stage") or 1) then
                player:SetAttribute("Stage", stageNum)
                player.RespawnLocation = cp
                local stats = player:FindFirstChild("leaderstats")
                local stageVal = stats and stats:FindFirstChild("Stage")
                if stageVal then stageVal.Value = stageNum end
            end
        end)
    end
end
""",
            encoding="utf-8",
        )

        (scripts_dir / "currency.lua").write_text(
            """-- currency.lua  (ServerScriptService)
-- Server-authoritative coins. The SERVER decides when and how many coins to
-- award. NEVER take the amount from the client (an exploiter would send a huge
-- value): https://create.roblox.com/docs/scripting/security/client-server-boundary

local Players = game:GetService("Players")

local function addCoins(player, amount)
    local leaderstats = player:FindFirstChild("leaderstats")
    if not leaderstats then return end
    local coins = leaderstats:FindFirstChild("Coins")
    if coins then
        coins.Value = coins.Value + amount
    end
end

-- Example: award coins when a player touches a coin part.
-- Put your coin parts inside a Folder named "Coins" in Workspace.
local coinsFolder = workspace:FindFirstChild("Coins")
if coinsFolder then
    for _, coin in ipairs(coinsFolder:GetChildren()) do
        if coin:IsA("BasePart") then
            coin.Touched:Connect(function(hit)
                local player = Players:GetPlayerFromCharacter(hit.Parent)
                if player then
                    addCoins(player, 10)  -- server decides the amount, not the client
                    coin:Destroy()
                end
            end)
        end
    end
end
""",
            encoding="utf-8",
        )

        (scripts_dir / "shop_server.lua").write_text(
            """-- shop_server.lua  (ServerScriptService)
-- The SERVER owns item prices and the whole purchase check. It looks the price
-- up itself and re-verifies coins server-side, so a client can never send a
-- fake price or buy something it can't afford.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Source of truth for prices (server-side only).
local ITEMS = {
    ["Speed Potion"] = 50,
    ["Double Jump"] = 100,
}

local buyEvent = Instance.new("RemoteEvent")  -- created on the SERVER so it replicates
buyEvent.Name = "BuyItem"
buyEvent.Parent = ReplicatedStorage

buyEvent.OnServerEvent:Connect(function(player, itemName)
    if typeof(itemName) ~= "string" then return end        -- validate input type
    local cost = ITEMS[itemName]
    if not cost then return end                            -- unknown item

    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or coins.Value < cost then return end     -- can't afford (server-checked)

    coins.Value = coins.Value - cost
    -- TODO: actually grant the item here (give a Tool, set an attribute, etc.)
end)
""",
            encoding="utf-8",
        )

        (scripts_dir / "shop.lua").write_text(
            """-- shop.lua  (StarterPlayerScripts / StarterGui LocalScript)
-- The client only REQUESTS a purchase by item name. It never sends the price --
-- the server owns prices and validates everything (see shop_server.lua).

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local buyEvent = ReplicatedStorage:WaitForChild("BuyItem")  -- created by the server

local function requestBuy(itemName)
    buyEvent:FireServer(itemName)  -- server looks up the cost + checks coins
end

-- Example: requestBuy("Speed Potion")
""",
            encoding="utf-8",
        )

        (project_dir / "README.md").write_text(
            f"""# {project_name}

A Roblox {game_type} game scaffold.

## Files (Luau)

Server scripts go in **ServerScriptService**; the LocalScript goes in **StarterPlayerScripts** (or StarterGui). Everything follows Roblox's server-authority model — the server is the source of truth and never trusts client input.

- `scripts/leaderstats.lua` — **ServerScriptService**: sets up the Coins/Level leaderboard (no saving).
- `scripts/datastore.lua` — **ServerScriptService**: sets up leaderstats **and saves/loads it** across sessions (DataStore). Use this **instead of** `leaderstats.lua` when you want progress to persist — don't run both.
- `scripts/checkpoints.lua` — **ServerScriptService**: obby spawns + checkpoints. Players respawn at the last checkpoint reached (stage persists via `datastore.lua`). Needs SpawnLocation parts in a `Checkpoints` folder in Workspace, named `1`, `2`, `3`…
- `scripts/currency.lua` — **ServerScriptService**: server awards coins (e.g. on collecting a coin part). The client never sends the amount.
- `scripts/shop_server.lua` — **ServerScriptService**: owns item prices, creates the `BuyItem` RemoteEvent, and validates every purchase server-side.
- `scripts/shop.lua` — **StarterPlayerScripts LocalScript**: requests a purchase by item name only (server owns the price).

## Next Steps

1. Open Roblox Studio, create/open a place.
2. Put the server scripts in **ServerScriptService** and `shop.lua` in **StarterPlayerScripts**. Use `datastore.lua` OR `leaderstats.lua`, not both.
3. For saving: **Game Settings > Security > Enable Studio Access to API Services** (DataStores need this + a published game).
4. Build the map; put coin parts in a `Coins` folder in Workspace; grant items in `shop_server.lua`'s TODO.
5. Publish, then configure game passes / developer products.

> Security: never trust the client. Keep prices, currency, and validation on the server.
> Docs: https://create.roblox.com/docs/scripting/security/client-server-boundary
""",
            encoding="utf-8",
        )

        return {
            "action": "create_project",
            "engine": "roblox",
            "project_dir": str(project_dir),
            "game_type": game_type,
            "files_created": ["scripts/leaderstats.lua", "scripts/datastore.lua", "scripts/checkpoints.lua", "scripts/currency.lua", "scripts/shop_server.lua", "scripts/shop.lua", "README.md"],
            "next_step": "In Roblox Studio: put the server scripts in ServerScriptService and shop.lua in StarterPlayerScripts.",
        }

    async def _generate_script(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        script_type = kwargs.get("script_type", "leaderstats")
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_ROBLOX_DIR / "MyRobloxGame")
        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        templates = {
            "leaderstats": (
                "leaderstats.lua",
                """-- leaderstats.lua
local Players = game:GetService("Players")
Players.PlayerAdded:Connect(function(player)
    local stats = Instance.new("Folder")
    stats.Name = "leaderstats"
    stats.Parent = player

    local coins = Instance.new("IntValue")
    coins.Name = "Coins"
    coins.Value = 0
    coins.Parent = stats
end)
""",
            ),
            "datastore": (
                "datastore.lua",
                """-- datastore.lua  (ServerScriptService)
-- Saves/loads Coins + Level across sessions. Sets up leaderstats too -- use this
-- INSTEAD of leaderstats.lua. In Studio enable "Studio Access to API Services".
-- Docs: https://create.roblox.com/docs/cloud-services/data-stores
local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local playerStore = DataStoreService:GetDataStore("PlayerData_v1")
local DEFAULT = { Coins = 0, Level = 1, Stage = 1 }

local function loadData(userId)
    local ok, result = pcall(function() return playerStore:GetAsync("Player_" .. userId) end)
    if ok then return result or table.clone(DEFAULT) end
    warn("DataStore load failed: " .. tostring(result)); return nil
end

local function saveData(userId, data)
    local ok, err = pcall(function()
        playerStore:UpdateAsync("Player_" .. userId, function() return data end)
    end)
    if not ok then warn("DataStore save failed: " .. tostring(err)) end
end

Players.PlayerAdded:Connect(function(player)
    local data = loadData(player.UserId)
    if data == nil then data = table.clone(DEFAULT); player:SetAttribute("DataLoadFailed", true) end
    player:SetAttribute("Stage", data.Stage or 1)
    local stats = Instance.new("Folder"); stats.Name = "leaderstats"
    local coins = Instance.new("IntValue"); coins.Name = "Coins"; coins.Value = data.Coins or 0; coins.Parent = stats
    local level = Instance.new("IntValue"); level.Name = "Level"; level.Value = data.Level or 1; level.Parent = stats
    stats.Parent = player
end)

local function savePlayer(player)
    if player:GetAttribute("DataLoadFailed") then return end
    local stats = player:FindFirstChild("leaderstats")
    if not stats then return end
    local coins, level = stats:FindFirstChild("Coins"), stats:FindFirstChild("Level")
    if coins and level then saveData(player.UserId, { Coins = coins.Value, Level = level.Value, Stage = player:GetAttribute("Stage") or 1 }) end
end

Players.PlayerRemoving:Connect(savePlayer)
game:BindToClose(function()
    for _, player in ipairs(Players:GetPlayers()) do task.spawn(savePlayer, player) end
    task.wait(3)
end)
""",
            ),
            "currency": (
                "currency.lua",
                """-- currency.lua  (ServerScriptService)
-- Server-authoritative: the server decides the amount, never the client.
local Players = game:GetService("Players")

local function addCoins(player, amount)
    local leaderstats = player:FindFirstChild("leaderstats")
    if not leaderstats then return end
    local coins = leaderstats:FindFirstChild("Coins")
    if coins then coins.Value = coins.Value + amount end
end

-- Example: award coins for touching a part inside a "Coins" folder in Workspace.
local coinsFolder = workspace:FindFirstChild("Coins")
if coinsFolder then
    for _, coin in ipairs(coinsFolder:GetChildren()) do
        if coin:IsA("BasePart") then
            coin.Touched:Connect(function(hit)
                local player = Players:GetPlayerFromCharacter(hit.Parent)
                if player then addCoins(player, 10); coin:Destroy() end
            end)
        end
    end
end
""",
            ),
            "shop_server": (
                "shop_server.lua",
                """-- shop_server.lua  (ServerScriptService)
-- Server owns prices + validates every purchase. Pairs with the shop LocalScript.
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local ITEMS = { ["Speed Potion"] = 50, ["Double Jump"] = 100 }  -- server-side prices

local buyEvent = Instance.new("RemoteEvent")  -- created on the server so it replicates
buyEvent.Name = "BuyItem"
buyEvent.Parent = ReplicatedStorage

buyEvent.OnServerEvent:Connect(function(player, itemName)
    if typeof(itemName) ~= "string" then return end
    local cost = ITEMS[itemName]
    if not cost then return end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or coins.Value < cost then return end
    coins.Value = coins.Value - cost
    -- TODO: grant the item to the player
end)
""",
            ),
            "shop": (
                "shop.lua",
                """-- shop.lua  (StarterPlayerScripts LocalScript)
-- Client only asks by item NAME; the server owns the price (see shop_server.lua).
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local buyEvent = ReplicatedStorage:WaitForChild("BuyItem")

local function requestBuy(itemName)
    buyEvent:FireServer(itemName)
end

-- Example: requestBuy("Speed Potion")
""",
            ),
            "teleport": (
                "teleport.lua",
                """-- teleport.lua  (server Script — TeleportService teleports players from the server)
local TeleportService = game:GetService("TeleportService")
local placeId = 0 -- replace with the target place ID

local function teleportPlayer(player)
    local ok, err = pcall(function()
        TeleportService:TeleportAsync(placeId, { player })
    end)
    if not ok then
        warn("Teleport failed: " .. tostring(err))
    end
end
""",
            ),
            "admin": (
                "admin.lua",
                """-- admin.lua
local Players = game:GetService("Players")
local admins = {1} -- replace with Roblox user IDs

local function isAdmin(player)
    return table.find(admins, player.UserId) ~= nil
end

Players.PlayerAdded:Connect(function(player)
    if isAdmin(player) then
        print(player.Name .. " is admin")
    end
end)
""",
            ),
            "gamepass": (
                "gamepass.lua",
                """-- gamepass.lua  (ServerScriptService)
-- Checks/grants a Game Pass perk. Replace GAME_PASS_ID with your pass ID.
-- Docs: https://create.roblox.com/docs/production/monetization/game-passes
local Players = game:GetService("Players")
local MarketplaceService = game:GetService("MarketplaceService")

local GAME_PASS_ID = 0  -- replace with your Game Pass ID

local function grantPass(player)
    if player:GetAttribute("VIP") then return end  -- only grant once
    player:SetAttribute("VIP", true)
    local function boost(char)
        local hum = char:WaitForChild("Humanoid")
        hum.WalkSpeed = 32
    end
    if player.Character then boost(player.Character) end
    player.CharacterAdded:Connect(boost)
end

local function checkPass(player)
    local ok, owns = pcall(function()
        return MarketplaceService:UserOwnsGamePassAsync(player.UserId, GAME_PASS_ID)
    end)
    if ok and owns then grantPass(player) end
end

Players.PlayerAdded:Connect(checkPass)

-- Grant right away if they buy it mid-game.
MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player, gamePassId, wasPurchased)
    if wasPurchased and gamePassId == GAME_PASS_ID then grantPass(player) end
end)

-- Prompt from a shop button: MarketplaceService:PromptGamePassPurchase(player, GAME_PASS_ID)
""",
            ),
            "developer_product": (
                "developer_product.lua",
                """-- developer_product.lua  (ServerScriptService)
-- Handles developer-product (consumable) purchases with the REQUIRED idempotent
-- ProcessReceipt flow, so a product is granted exactly once even on retries.
-- Docs: https://create.roblox.com/docs/reference/engine/classes/MarketplaceService#ProcessReceipt
local Players = game:GetService("Players")
local MarketplaceService = game:GetService("MarketplaceService")
local DataStoreService = game:GetService("DataStoreService")

local purchaseHistory = DataStoreService:GetDataStore("PurchaseHistory")

-- Map each Product ID to what it grants. Replace the IDs with your products.
local PRODUCTS = {
    [0] = function(player)  -- e.g. a "100 Coins" product
        local stats = player:FindFirstChild("leaderstats")
        local coins = stats and stats:FindFirstChild("Coins")
        if coins then coins.Value = coins.Value + 100 end
    end,
}

MarketplaceService.ProcessReceipt = function(receiptInfo)
    local player = Players:GetPlayerByUserId(receiptInfo.PlayerId)
    if not player then
        return Enum.ProductPurchaseDecision.NotProcessedYet  -- retry when they rejoin
    end

    local grant = PRODUCTS[receiptInfo.ProductId]
    if not grant then
        return Enum.ProductPurchaseDecision.PurchaseGranted  -- unknown product; stop retrying
    end

    -- Idempotent: keyed on the unique PurchaseId so a receipt only grants once.
    local key = "receipt_" .. receiptInfo.PurchaseId
    local ok, err = pcall(function()
        purchaseHistory:UpdateAsync(key, function(alreadyGranted)
            if alreadyGranted then return alreadyGranted end
            grant(player)
            return true
        end)
    end)

    if ok then
        return Enum.ProductPurchaseDecision.PurchaseGranted
    end
    warn("ProcessReceipt error: " .. tostring(err))
    return Enum.ProductPurchaseDecision.NotProcessedYet  -- DataStore failed; retry later
end

-- Prompt from a shop button: MarketplaceService:PromptProductPurchase(player, PRODUCT_ID)
""",
            ),
            "round": (
                "round.lua",
                """-- round.lua  (ServerScriptService)
-- Round loop: intermission -> round -> repeat. Publishes status + time left to
-- ReplicatedStorage so a client UI can display it.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local INTERMISSION = 15
local ROUND_LENGTH = 60

local status = Instance.new("StringValue")
status.Name = "RoundStatus"; status.Value = "Waiting"; status.Parent = ReplicatedStorage
local timeLeft = Instance.new("IntValue")
timeLeft.Name = "TimeLeft"; timeLeft.Parent = ReplicatedStorage

local function countdown(seconds, label)
    status.Value = label
    for t = seconds, 1, -1 do
        timeLeft.Value = t
        task.wait(1)
    end
    timeLeft.Value = 0
end

local function startRound()
    -- TODO: teleport players to the arena, give tools, etc.
    countdown(ROUND_LENGTH, "In Round")
    -- TODO: decide a winner, award coins, reset the map
end

task.spawn(function()
    while true do
        if #Players:GetPlayers() >= 1 then
            countdown(INTERMISSION, "Intermission")
            startRound()
        else
            status.Value = "Waiting for players"
            task.wait(2)
        end
    end
end)
""",
            ),
            "checkpoints": (
                "checkpoints.lua",
                """-- checkpoints.lua  (ServerScriptService)
-- Obby spawns + checkpoints. Put SpawnLocation parts in a Folder named
-- "Checkpoints" in Workspace, named "1", "2", "3"... (1 = the start). Players
-- respawn at the highest checkpoint they've reached. Persists if you save the
-- "Stage" attribute in datastore.lua.
-- Docs: https://create.roblox.com/docs/tutorials/curriculums/gameplay-scripting/spawn-respawn
local Players = game:GetService("Players")
local checkpoints = workspace:WaitForChild("Checkpoints")

local function spawnAtStage(player, char)
    local stage = player:GetAttribute("Stage") or 1
    local cp = checkpoints:FindFirstChild(tostring(stage))
    if cp then
        player.RespawnLocation = cp  -- future respawns land here
        local root = char:WaitForChild("HumanoidRootPart")
        root.CFrame = cp.CFrame + Vector3.new(0, 3, 0)  -- move them there now
    end
end

Players.PlayerAdded:Connect(function(player)
    if player:GetAttribute("Stage") == nil then
        player:SetAttribute("Stage", 1)
    end
    -- optional visible "Stage" on the leaderboard
    local stats = player:FindFirstChild("leaderstats") or player:WaitForChild("leaderstats", 5)
    if stats and not stats:FindFirstChild("Stage") then
        local stageVal = Instance.new("IntValue")
        stageVal.Name = "Stage"
        stageVal.Value = player:GetAttribute("Stage") or 1
        stageVal.Parent = stats
    end
    player.CharacterAdded:Connect(function(char)
        spawnAtStage(player, char)
    end)
end)

-- Touching a higher-numbered checkpoint advances the player's stage.
for _, cp in ipairs(checkpoints:GetChildren()) do
    local stageNum = tonumber(cp.Name)
    if stageNum then
        cp.Touched:Connect(function(hit)
            local player = Players:GetPlayerFromCharacter(hit.Parent)
            if not player then return end
            if stageNum > (player:GetAttribute("Stage") or 1) then
                player:SetAttribute("Stage", stageNum)
                player.RespawnLocation = cp
                local stats = player:FindFirstChild("leaderstats")
                local stageVal = stats and stats:FindFirstChild("Stage")
                if stageVal then stageVal.Value = stageNum end
            end
        end)
    end
end
""",
            ),
        }

        if script_type not in templates:
            return {"error": f"Unknown script_type: {script_type}"}

        filename, content = templates[script_type]
        path = scripts_dir / filename
        path.write_text(content, encoding="utf-8")

        return {
            "action": "generate_script",
            "script_type": script_type,
            "file": str(path),
        }

    async def _wave_survival(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Scaffold the complete official Roblox 'Wave Survival' game.

        Follows the Roblox reference workflow: a Script-Sync folder layout with
        ``.server.luau`` / ``.client.luau`` files and a server-authoritative design
        (the server owns enemies, damage, waves and win-state; the client only
        renders and requests). Drop these folders into the ones Script Sync binds
        (ServerScriptService / StarterPlayerScripts) and it runs -- no pre-made
        assets needed (enemies, the HUD and the laser are all built in code).
        Spec: enemies spawn in growing waves and chase the nearest living player,
        exploding on contact; a laser kills in two hits; dead players spectate as
        ghosts the enemies ignore; the last survivor is announced and it restarts
        at wave 1.

        The ``theme`` arg picks the flavor: ``scifi`` (default, this method) or
        ``medieval`` (swords vs an invading army -- see ``_wave_survival_medieval``).
        """
        theme = str(kwargs.get("theme", "scifi")).strip().lower()
        if theme in ("medieval", "sword", "swords", "knight", "fantasy", "siege", "army"):
            return await self._wave_survival_medieval(kwargs)

        project_name = kwargs.get("project_name", "WaveSurvival")
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_ROBLOX_DIR) / project_name
        server_dir = project_dir / "ServerScriptService"
        client_dir = project_dir / "StarterPlayerScripts"
        shared_dir = project_dir / "ReplicatedStorage"
        for d in (server_dir, client_dir, shared_dir):
            d.mkdir(parents=True, exist_ok=True)

        (server_dir / "GameServer.server.luau").write_text(
            """--!strict
-- GameServer.server.luau  (ServerScriptService)
-- Wave-survival server. AUTHORITATIVE for enemies, damage, waves and win-state --
-- the client only renders and requests, so nothing here trusts client input.
-- Built to match the Roblox "Wave Survival" reference (create.roblox.com/docs).
--
-- Enemies spawn in growing waves around living players and chase the nearest one,
-- exploding on contact for damage. A laser kills in two hits. Dead players become
-- ghosts the enemies ignore. The last survivor is announced, then it restarts.
-- Everything (enemies, HUD, laser) is built in code -- no pre-made assets needed.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- ===== Remotes (created here so the client can WaitForChild them) =====
local function remote(name: string): RemoteEvent
	local r = ReplicatedStorage:FindFirstChild(name)
	if not r then
		r = Instance.new("RemoteEvent")
		r.Name = name
		r.Parent = ReplicatedStorage
	end
	return r :: RemoteEvent
end
local FireLaser = remote("FireLaser") -- client -> server: origin, direction
local Hud       = remote("Hud")       -- server -> client: { wave = , kills = }
local YouDied   = remote("YouDied")   -- server -> one client
local Winner    = remote("Winner")    -- server -> all clients: name

-- ===== Tunables =====
local ENEMY_HEALTH = 2    -- two laser shots kill an enemy
local ENEMY_SPEED  = 14
local ENEMY_DAMAGE = 25   -- damage dealt when an enemy reaches a player
local SPAWN_RADIUS = 40
local BASE_ENEMIES = 3    -- enemies in wave 1
local PER_WAVE     = 2    -- extra enemies each wave
local WAVE_PAUSE   = 4    -- seconds of calm between waves

-- ===== State =====
local enemies: {[Model]: boolean} = {}
local enemyCount = 0
local kills: {[Player]: number} = {}
local currentWave = 0
local running = false

-- forward declarations (assigned near the bottom)
local startGame: () -> ()
local restartGame: () -> ()
local checkWin: () -> ()

-- ===== Helpers =====
local function isAlive(p: Player): boolean
	if p:GetAttribute("Spectating") then return false end
	local char = p.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	return hum ~= nil and hum.Health > 0
end

local function alivePlayers(): {Player}
	local list = {}
	for _, p in ipairs(Players:GetPlayers()) do
		if isAlive(p) then table.insert(list, p) end
	end
	return list
end

local function nearestRoot(pos: Vector3): BasePart?
	local best: BasePart? = nil
	local bestDist: number? = nil
	for _, p in ipairs(alivePlayers()) do
		local root = p.Character and p.Character:FindFirstChild("HumanoidRootPart")
		if root then
			local d = (root.Position - pos).Magnitude
			if bestDist == nil or d < bestDist then
				best, bestDist = root, d
			end
		end
	end
	return best
end

-- ===== Enemies (built in code -- no asset required) =====
local function removeEnemy(model: Model)
	if enemies[model] then
		enemies[model] = nil
		enemyCount -= 1
		model:Destroy()
	end
end

local function spawnEnemy(pos: Vector3)
	local model = Instance.new("Model")
	model.Name = "Enemy"

	local root = Instance.new("Part")
	root.Name = "HumanoidRootPart"
	root.Size = Vector3.new(2, 3, 1)
	root.Color = Color3.fromRGB(200, 45, 45)
	root.CFrame = CFrame.new(pos)
	root.Parent = model
	model.PrimaryPart = root

	local head = Instance.new("Part") -- little head so it reads as a creature
	head.Name = "Head"
	head.Shape = Enum.PartType.Ball
	head.Size = Vector3.new(1.2, 1.2, 1.2)
	head.Color = Color3.fromRGB(150, 25, 25)
	head.CanCollide = false
	head.CFrame = root.CFrame * CFrame.new(0, 2.1, 0)
	head.Parent = model
	local weld = Instance.new("WeldConstraint")
	weld.Part0, weld.Part1 = root, head
	weld.Parent = root

	local hum = Instance.new("Humanoid")
	hum.MaxHealth = ENEMY_HEALTH
	hum.Health = ENEMY_HEALTH
	hum.WalkSpeed = ENEMY_SPEED
	hum.Parent = model

	model:SetAttribute("Exploded", false)
	model.Parent = workspace
	enemies[model] = true
	enemyCount += 1

	hum.Died:Connect(function() removeEnemy(model) end)

	-- Reaching a living player: explode, deal damage, and die on contact.
	root.Touched:Connect(function(hit)
		if model:GetAttribute("Exploded") then return end
		local player = Players:GetPlayerFromCharacter(hit.Parent)
		if player and isAlive(player) then
			model:SetAttribute("Exploded", true)
			local victim = hit.Parent and hit.Parent:FindFirstChildOfClass("Humanoid")
			if victim then victim:TakeDamage(ENEMY_DAMAGE) end
			local blast = Instance.new("Explosion")
			blast.Position = root.Position
			blast.BlastPressure = 0   -- visual only; don't fling the map around
			blast.BlastRadius = 4
			blast.Parent = workspace
			removeEnemy(model)
		end
	end)
end

-- ===== Enemy AI: chase the nearest living player =====
task.spawn(function()
	while true do
		for model in pairs(enemies) do
			local root = model.PrimaryPart
			local hum = model:FindFirstChildOfClass("Humanoid")
			if root and hum then
				local target = nearestRoot(root.Position)
				if target then hum:MoveTo(target.Position) end
			end
		end
		task.wait(0.3)
	end
end)

-- ===== Laser hits: server raycasts + validates; two hits kill =====
FireLaser.OnServerEvent:Connect(function(player, origin, direction)
	if not isAlive(player) then return end
	if typeof(origin) ~= "Vector3" or typeof(direction) ~= "Vector3" then return end
	local dir = direction
	if dir.Magnitude > 500 then dir = dir.Unit * 500 end -- clamp; never trust the client

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { player.Character }
	local hit = workspace:Raycast(origin, dir, params)
	if not hit then return end

	local model = hit.Instance:FindFirstAncestorOfClass("Model")
	if model and enemies[model] then
		local hum = model:FindFirstChildOfClass("Humanoid")
		if hum and hum.Health > 0 then
			hum:TakeDamage(1) -- ENEMY_HEALTH = 2, so two shots kill
			if hum.Health <= 0 then
				kills[player] = (kills[player] or 0) + 1
				Hud:FireClient(player, { kills = kills[player] })
			end
		end
	end
end)

-- ===== Player lifecycle: death -> spectator, then check for a winner =====
Players.PlayerAdded:Connect(function(player)
	kills[player] = 0
	player:SetAttribute("Spectating", false)
	player.CharacterAdded:Connect(function(char)
		local hum = char:WaitForChild("Humanoid") :: Humanoid
		if player:GetAttribute("Spectating") then
			-- ghost look while spectating; enemies already ignore via isAlive()
			task.defer(function()
				for _, d in ipairs(char:GetDescendants()) do
					if d:IsA("BasePart") then
						d.Transparency = 0.7
						d.CanCollide = false
					end
				end
				local hl = Instance.new("Highlight")
				hl.FillColor = Color3.fromRGB(120, 160, 255)
				hl.FillTransparency = 0.5
				hl.Parent = char
			end)
		end
		hum.Died:Connect(function()
			if not player:GetAttribute("Spectating") then
				player:SetAttribute("Spectating", true)
				YouDied:FireClient(player)
				checkWin()
			end
		end)
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	kills[player] = nil
	checkWin()
end)

-- ===== Win / restart =====
checkWin = function()
	if not running then return end
	if #Players:GetPlayers() == 0 then return end
	local alive = alivePlayers()
	if #alive <= 1 then
		local winnerName = if #alive == 1 then alive[1].Name else "Nobody"
		Winner:FireAllClients(winnerName)
		restartGame()
	end
end

restartGame = function()
	running = false
	task.wait(3) -- let players read the winner banner
	for model in pairs(enemies) do removeEnemy(model) end
	currentWave = 0
	for _, p in ipairs(Players:GetPlayers()) do
		p:SetAttribute("Spectating", false)
		kills[p] = 0
		Hud:FireClient(p, { kills = 0 })
		p:LoadCharacter() -- respawn everyone as a fighter
	end
	task.wait(1)
	startGame()
end

-- ===== Wave loop =====
startGame = function()
	if running then return end
	running = true
	task.spawn(function()
		while running do
			currentWave += 1
			Hud:FireAllClients({ wave = currentWave })
			local count = BASE_ENEMIES + (currentWave - 1) * PER_WAVE
			for _ = 1, count do
				if not running then break end
				local targets = alivePlayers()
				local center = Vector3.new(0, 5, 0)
				if #targets > 0 then
					local anchor = targets[math.random(1, #targets)]
					local root = anchor.Character and anchor.Character:FindFirstChild("HumanoidRootPart")
					if root then center = root.Position end
				end
				local angle = math.random() * math.pi * 2
				local offset = Vector3.new(math.cos(angle), 0, math.sin(angle)) * SPAWN_RADIUS
				spawnEnemy(center + offset + Vector3.new(0, 3, 0))
				task.wait(0.25)
			end
			-- wait out the wave (all enemies cleared)
			while running and enemyCount > 0 do task.wait(0.5) end
			if not running then break end
			task.wait(WAVE_PAUSE) -- calm between waves
		end
	end)
end

-- Kick off once at least one player is present.
task.spawn(function()
	while #Players:GetPlayers() == 0 do task.wait(1) end
	startGame()
end)
""",
            encoding="utf-8",
        )

        (client_dir / "Client.client.luau").write_text(
            """--!strict
-- Client.client.luau  (StarterPlayerScripts)
-- HUD (wave, kills, "You Died" / winner) and a click-to-fire laser with a beam.
-- The client only ASKS to fire -- the server raycasts and applies damage, so an
-- exploiter can't fake kills. Built to match the Roblox "Wave Survival" reference.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local Debris = game:GetService("Debris")

local player = Players.LocalPlayer
local mouse = player:GetMouse()

local FireLaser = ReplicatedStorage:WaitForChild("FireLaser")
local Hud       = ReplicatedStorage:WaitForChild("Hud")
local YouDied   = ReplicatedStorage:WaitForChild("YouDied")
local Winner    = ReplicatedStorage:WaitForChild("Winner")

-- ===== HUD (built in code) =====
local gui = Instance.new("ScreenGui")
gui.Name = "WaveHUD"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")

local function makeLabel(pos: UDim2, size: UDim2): TextLabel
	local l = Instance.new("TextLabel")
	l.BackgroundTransparency = 1
	l.TextColor3 = Color3.new(1, 1, 1)
	l.TextStrokeTransparency = 0.3
	l.Font = Enum.Font.GothamBold
	l.TextScaled = true
	l.Position = pos
	l.Size = size
	l.Parent = gui
	return l
end

local waveLabel = makeLabel(UDim2.fromScale(0.02, 0.02), UDim2.fromScale(0.25, 0.06))
waveLabel.TextXAlignment = Enum.TextXAlignment.Left
waveLabel.Text = "Wave 1"

local killLabel = makeLabel(UDim2.fromScale(0.02, 0.09), UDim2.fromScale(0.25, 0.05))
killLabel.TextXAlignment = Enum.TextXAlignment.Left
killLabel.Text = "Kills: 0"

local banner = makeLabel(UDim2.fromScale(0.25, 0.4), UDim2.fromScale(0.5, 0.15))
banner.TextColor3 = Color3.fromRGB(255, 80, 80)
banner.Text = ""

Hud.OnClientEvent:Connect(function(data)
	if type(data) ~= "table" then return end
	if data.wave then
		waveLabel.Text = "Wave " .. tostring(data.wave)
		banner.Text = "" -- clear "You Died" when a fresh round starts
		banner.TextColor3 = Color3.fromRGB(255, 80, 80)
	end
	if data.kills then killLabel.Text = "Kills: " .. tostring(data.kills) end
end)

YouDied.OnClientEvent:Connect(function()
	banner.TextColor3 = Color3.fromRGB(255, 80, 80)
	banner.Text = "You Died"
end)

Winner.OnClientEvent:Connect(function(name)
	banner.TextColor3 = Color3.fromRGB(120, 255, 140)
	banner.Text = tostring(name) .. " wins!"
	task.delay(3, function()
		banner.TextColor3 = Color3.fromRGB(255, 80, 80)
		banner.Text = ""
	end)
end)

-- ===== Laser: click (or tap) to fire =====
local COOLDOWN = 0.25
local lastShot = 0.0

local function drawBeam(from: Vector3, to: Vector3)
	local beam = Instance.new("Part")
	beam.Anchored = true
	beam.CanCollide = false
	beam.CastShadow = false
	beam.Material = Enum.Material.Neon
	beam.Color = Color3.fromRGB(0, 200, 255)
	local dist = (to - from).Magnitude
	beam.Size = Vector3.new(0.2, 0.2, dist)
	beam.CFrame = CFrame.lookAt(from, to) * CFrame.new(0, 0, -dist / 2)
	beam.Parent = workspace
	Debris:AddItem(beam, 0.08)
end

local function fire()
	if player:GetAttribute("Spectating") then return end -- ghosts don't shoot
	local now = os.clock()
	if now - lastShot < COOLDOWN then return end
	lastShot = now

	local char = player.Character
	local root = char and char:FindFirstChild("HumanoidRootPart")
	if not root then return end

	local origin = root.Position + Vector3.new(0, 1.5, 0)
	local target = mouse.Hit.Position
	local direction = target - origin
	FireLaser:FireServer(origin, direction)
	drawBeam(origin, target)
end

UserInputService.InputBegan:Connect(function(input, processed)
	if processed then return end
	if input.UserInputType == Enum.UserInputType.MouseButton1
		or input.UserInputType == Enum.UserInputType.Touch then
		fire()
	end
end)
""",
            encoding="utf-8",
        )

        (shared_dir / ".gitkeep").write_text(
            "-- Remotes (FireLaser, Hud, YouDied, Winner) are created at runtime by\n"
            "-- GameServer.server.luau, so no shared modules are needed for this game.\n",
            encoding="utf-8",
        )

        (project_dir / "README.md").write_text(
            f"""# {project_name} -- Wave Survival

The complete Roblox **Wave Survival** game, scaffolded to the official reference
standard: a **Script Sync** folder layout with `.server.luau` / `.client.luau`
files and a **server-authoritative** design (the server owns enemies, damage,
waves and the win-state; the client only renders and requests). No pre-made
assets are needed -- enemies, the HUD and the laser are all built in code.

## What it does

- Enemies spawn in a ring around living players and **chase the nearest one**.
- Enemies **explode on contact**, dealing damage, then despawn.
- A **laser** (click / tap to fire) kills an enemy in **two hits** -- the server
  raycasts and applies damage, so kills can't be faked by the client.
- Waves **grow** (base 3, then +2 each wave) with a short **pause** between them.
- On death a player becomes a **ghost spectator** the enemies ignore.
- The **last survivor is announced**, then the game **restarts at wave 1**.
- A HUD shows the **wave number**, your **kill count**, and **"You Died"** / winner.

## Files (Script Sync layout)

- `ServerScriptService/GameServer.server.luau` -- the whole server: waves, enemy
  AI, laser damage, spectator mode, winner/restart. Creates the RemoteEvents.
- `StarterPlayerScripts/Client.client.luau` -- HUD + click-to-fire laser + beam.
- `ReplicatedStorage/` -- empty (remotes are created at runtime by the server).

## Build it the reference way (Script Sync + MCP)

1. In Studio: **File -> Beta Features -> Script Sync**, enable it, restart.
2. Right-click **ServerScriptService -> Script Sync -> Sync to** and pick the
   `{project_name}` folder (not the subfolders -- the names already match).
   Repeat for **StarterPlayerScripts** and **ReplicatedStorage**.
3. The two scripts appear in Studio automatically. Press **Play**.
4. (Optional) Enable the Studio **MCP** connection so an AI agent can start
   playtests, read the console and create StarterGui/StarterPack objects -- the
   parts Script Sync can't reach.

## Verify (from the reference checklist)

- [ ] Enemies spawn and walk toward you each wave.
- [ ] Two laser hits kill an enemy; the kill counter goes up.
- [ ] Touching you deals damage / an enemy explosion is visible.
- [ ] Dying shows **"You Died"** and turns you into a ghost enemies ignore.
- [ ] Clearing a wave pauses, then the next wave has more enemies.
- [ ] Last survivor is announced and the game restarts at wave 1.

> Security: the server never trusts the client. Damage, health, waves and the
> win-state all live on the server. Docs:
> https://create.roblox.com/docs/scripting/security/client-server-boundary
""",
            encoding="utf-8",
        )

        return {
            "action": "wave_survival",
            "engine": "roblox",
            "project_dir": str(project_dir),
            "files_created": [
                "ServerScriptService/GameServer.server.luau",
                "StarterPlayerScripts/Client.client.luau",
                "ReplicatedStorage/.gitkeep",
                "README.md",
            ],
            "next_step": (
                "In Roblox Studio enable Script Sync (File > Beta Features), then "
                "Sync ServerScriptService and StarterPlayerScripts to this folder and press Play."
            ),
        }

    async def _wave_survival_medieval(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Scaffold the medieval 'siege' flavor of wave survival.

        Same reference standard as the sci-fi build (Script-Sync layout,
        server-authoritative, everything built in code) re-themed to a castle
        defense with **real pathfinding through a gatehouse**: a fully-walled stone
        castle with a single **gate** is raised in code; an invading army of melee
        **soldiers** and ranged **archers** uses ``PathfindingService`` to navigate
        around the walls, funnel through the gate, and assault a **keep you must
        protect**. Your sword fells a soldier in three hits (an archer in two). You
        lose when the keep's health hits zero or every defender falls -- then the
        siege resets at Wave I. Score is the number of waves you hold.
        """
        project_name = kwargs.get("project_name", "MedievalSiege")
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_ROBLOX_DIR) / project_name
        server_dir = project_dir / "ServerScriptService"
        client_dir = project_dir / "StarterPlayerScripts"
        shared_dir = project_dir / "ReplicatedStorage"
        for d in (server_dir, client_dir, shared_dir):
            d.mkdir(parents=True, exist_ok=True)

        (server_dir / "GameServer.server.luau").write_text(
            """--!strict
-- GameServer.server.luau  (ServerScriptService)
-- MEDIEVAL SIEGE -- defend the castle. A fully-walled stone castle with a single
-- GATE is raised in code. An invading army of melee SOLDIERS and ranged ARCHERS
-- uses PathfindingService to navigate around the walls, funnel through the gate,
-- and assault the KEEP you must protect. AUTHORITATIVE server: it owns the enemies,
-- all pathing and damage, the keep's health, the wave schedule and the lose-state
-- -- the client only renders and requests a swing. Everything (the castle, the
-- enemies, the sword, the HUD) is built in code, so it runs with no imported assets.
--
-- Loop: each wave, an army spawns beyond the gate and paths in through it.
-- Soldiers march to the keep and hack at it (or at any defender who blocks them);
-- archers hold at range and loose arrows over the wall. Cut them down before the
-- keep falls. You lose when the keep's health reaches zero or every defender has
-- fallen -- then the siege resets at Wave I. How many waves can you hold?

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Debris = game:GetService("Debris")
local TweenService = game:GetService("TweenService")
local PathfindingService = game:GetService("PathfindingService")

-- ===== Remotes (created here so the client can WaitForChild them) =====
local function remote(name: string): RemoteEvent
	local r = ReplicatedStorage:FindFirstChild(name)
	if not r then
		r = Instance.new("RemoteEvent")
		r.Name = name
		r.Parent = ReplicatedStorage
	end
	return r :: RemoteEvent
end
local SwingSword = remote("SwingSword") -- client -> server: "I swung"
local Hud        = remote("Hud")        -- server -> client: { wave=, kills=, keep=, keepMax= }
local YouDied    = remote("YouDied")    -- server -> one client
local Defeat     = remote("Defeat")     -- server -> all clients: message, wavesHeld

-- ===== Tunables =====
local SOLDIER_HEALTH   = 3     -- three sword hits
local ARCHER_HEALTH    = 2     -- two sword hits (lightly armored)
local SOLDIER_SPEED    = 12
local ARCHER_SPEED     = 13
local SOLDIER_DAMAGE   = 12    -- to a defender
local SOLDIER_KEEP_DMG = 10    -- to the keep
local ARCHER_KEEP_DMG  = 6     -- per arrow into the keep
local SOLDIER_RANGE    = 6     -- melee reach
local SOLDIER_COOLDOWN = 1.5
local ARCHER_STANDOFF  = 45    -- archers hold roughly this far from the keep and volley
local ARCHER_COOLDOWN  = 2.2
local SWORD_DAMAGE     = 1     -- x3 fells a soldier, x2 an archer
local SWORD_RANGE      = 9
local SWORD_ARC        = 0.35  -- dot threshold (~140-degree swing arc in front)
local SWORD_COOLDOWN   = 0.6
local BASE_SOLDIERS    = 4     -- soldiers in Wave I
local PER_WAVE         = 2     -- extra soldiers each wave
local MAX_ARCHERS      = 6     -- archer cap per wave
local WAVE_PAUSE       = 6     -- seconds while the horde regroups
local SPAWN_RADIUS     = 75    -- army musters beyond the gate
local CASTLE_ORIGIN    = Vector3.new(0, 0, 0)
local KEEP_MAX_HP      = 500   -- the castle you defend
-- the muster point the army paths to: just inside the gate, in front of the keep
local KEEP_TARGET      = CASTLE_ORIGIN + Vector3.new(0, 2, 9)
-- how the pathfinder sizes an enemy (so it fits through the gate, not over walls)
local AGENT_PARAMS = {
	AgentRadius = 2.5,
	AgentHeight = 5,
	AgentCanJump = false,
	AgentCanClimb = false,
	WaypointSpacing = 6,
}

-- ===== State =====
local enemies: {[Model]: boolean} = {}
local enemyCount = 0
local kills: {[Player]: number} = {}
local currentWave = 0
local running = false
local defeated = false
local keepHealth = KEEP_MAX_HP
local keepPart: BasePart? = nil
local castleModel: Model? = nil

-- forward declarations (assigned near the bottom)
local startGame: () -> ()
local restartGame: () -> ()
local loseSiege: (msg: string) -> ()

-- ===== Helpers =====
local function isAlive(p: Player): boolean
	if p:GetAttribute("Spectating") then return false end
	local char = p.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	return hum ~= nil and hum.Health > 0
end

local function alivePlayers(): {Player}
	local list = {}
	for _, p in ipairs(Players:GetPlayers()) do
		if isAlive(p) then table.insert(list, p) end
	end
	return list
end

local function nearestRoot(pos: Vector3): BasePart?
	local best: BasePart? = nil
	local bestDist: number? = nil
	for _, p in ipairs(alivePlayers()) do
		local root = p.Character and p.Character:FindFirstChild("HumanoidRootPart")
		if root then
			local d = (root.Position - pos).Magnitude
			if bestDist == nil or d < bestDist then
				best, bestDist = root, d
			end
		end
	end
	return best
end

-- ===== The castle (built in code: four walls, one gate, a keep to defend) =====
local function block(parent: Instance, name: string, size: Vector3, cf: CFrame, color: Color3, mat: Enum.Material): BasePart
	local p = Instance.new("Part")
	p.Name = name
	p.Anchored = true
	p.Size = size
	p.CFrame = cf
	p.Color = color
	p.Material = mat
	p.Parent = parent
	return p
end

local function buildCastle()
	if castleModel then castleModel:Destroy() end
	local m = Instance.new("Model")
	m.Name = "Castle"

	local stone = Color3.fromRGB(120, 120, 125)
	local timber = Color3.fromRGB(95, 70, 45)
	local span = 44
	local wallH, wallT = 12, 2
	local o = CASTLE_ORIGIN

	-- courtyard floor (kept flush with the ground so the pathfinder walks onto it)
	block(m, "Courtyard", Vector3.new(span, 0.4, span), CFrame.new(o + Vector3.new(0, 0.2, 0)), Color3.fromRGB(85, 95, 75), Enum.Material.Grass)
	-- back + side walls (fully enclosed except the gate)
	block(m, "WallBack", Vector3.new(span, wallH, wallT), CFrame.new(o + Vector3.new(0, wallH / 2, -span / 2)), stone, Enum.Material.Concrete)
	block(m, "WallLeft", Vector3.new(wallT, wallH, span), CFrame.new(o + Vector3.new(-span / 2, wallH / 2, 0)), stone, Enum.Material.Concrete)
	block(m, "WallRight", Vector3.new(wallT, wallH, span), CFrame.new(o + Vector3.new(span / 2, wallH / 2, 0)), stone, Enum.Material.Concrete)
	-- FRONT wall (+Z) split into two segments, leaving a central gate opening
	local gateW = 12
	local segW = (span - gateW) / 2
	block(m, "WallFrontL", Vector3.new(segW, wallH, wallT), CFrame.new(o + Vector3.new(-(gateW + segW) / 2, wallH / 2, span / 2)), stone, Enum.Material.Concrete)
	block(m, "WallFrontR", Vector3.new(segW, wallH, wallT), CFrame.new(o + Vector3.new((gateW + segW) / 2, wallH / 2, span / 2)), stone, Enum.Material.Concrete)
	-- gatehouse: timber posts + lintel framing the opening
	block(m, "GatePostL", Vector3.new(2, wallH + 3, 4), CFrame.new(o + Vector3.new(-(gateW / 2 + 1), (wallH + 3) / 2, span / 2)), timber, Enum.Material.WoodPlanks)
	block(m, "GatePostR", Vector3.new(2, wallH + 3, 4), CFrame.new(o + Vector3.new((gateW / 2 + 1), (wallH + 3) / 2, span / 2)), timber, Enum.Material.WoodPlanks)
	block(m, "GateLintel", Vector3.new(gateW + 6, 2.5, 4), CFrame.new(o + Vector3.new(0, wallH + 1.75, span / 2)), timber, Enum.Material.WoodPlanks)
	-- raised portcullis bars (cosmetic, non-colliding, up in the arch)
	for k = -2, 2 do
		local bar = block(m, "PortBar", Vector3.new(0.4, 3, 0.4), CFrame.new(o + Vector3.new(k * 2.4, wallH + 0.5, span / 2)), Color3.fromRGB(70, 70, 75), Enum.Material.Metal)
		bar.CanCollide = false
	end
	-- corner towers
	for _, c in ipairs({ Vector3.new(1, 0, 1), Vector3.new(1, 0, -1), Vector3.new(-1, 0, 1), Vector3.new(-1, 0, -1) }) do
		block(m, "Tower", Vector3.new(6, 18, 6), CFrame.new(o + Vector3.new(c.X * span / 2, 9, c.Z * span / 2)), stone, Enum.Material.Concrete)
	end
	-- the keep -- the core you protect
	local keep = block(m, "Keep", Vector3.new(12, 20, 12), CFrame.new(o + Vector3.new(0, 10, 0)), Color3.fromRGB(140, 130, 110), Enum.Material.Brick)
	block(m, "Banner", Vector3.new(0.4, 6, 3), CFrame.new(o + Vector3.new(0, 24, 0)), Color3.fromRGB(180, 40, 40), Enum.Material.Fabric)
	-- defenders spawn in the courtyard, between the gate and the keep
	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "DefenderSpawn"
	spawn.Anchored = true
	spawn.Size = Vector3.new(8, 1, 8)
	spawn.CFrame = CFrame.new(o + Vector3.new(0, 1, 15))
	spawn.Color = Color3.fromRGB(80, 80, 90)
	spawn.Neutral = true
	spawn.Parent = m

	m.Parent = workspace
	castleModel = m
	keepPart = keep
	keepHealth = KEEP_MAX_HP
end

local function damageKeep(amount: number)
	if keepHealth <= 0 then return end
	keepHealth = math.max(0, keepHealth - amount)
	Hud:FireAllClients({ keep = keepHealth, keepMax = KEEP_MAX_HP })
	if keepPart then
		local orig = keepPart.Color
		keepPart.Color = Color3.fromRGB(200, 70, 60)
		task.delay(0.1, function()
			if keepPart and keepPart.Parent then keepPart.Color = orig end
		end)
	end
	if keepHealth <= 0 then
		loseSiege("The castle has fallen!")
	end
end

-- ===== A cosmetic arrow that flies from an archer to its mark =====
local function fireArrow(fromPos: Vector3, targetPos: Vector3)
	local arrow = Instance.new("Part")
	arrow.Name = "Arrow"
	arrow.Size = Vector3.new(0.2, 0.2, 3)
	arrow.Color = Color3.fromRGB(90, 60, 30)
	arrow.Material = Enum.Material.Wood
	arrow.Anchored = true
	arrow.CanCollide = false
	arrow.CFrame = CFrame.lookAt(fromPos, targetPos)
	arrow.Parent = workspace
	local dist = (targetPos - fromPos).Magnitude
	local flight = math.clamp(dist / 120, 0.15, 1.0)
	local dir = targetPos - fromPos
	local goal = if dir.Magnitude > 0.001 then CFrame.lookAt(targetPos, targetPos + dir) else CFrame.new(targetPos)
	TweenService:Create(arrow, TweenInfo.new(flight, Enum.EasingStyle.Linear), { CFrame = goal }):Play()
	Debris:AddItem(arrow, flight + 0.1)
end

-- ===== Attacks: strike a defender or the keep when in reach; archers volley =====
-- Returns true if the enemy is in position to attack (so it should stop moving).
local function attackTick(model: Model, root: BasePart, isArcher: boolean): boolean
	local now = os.clock()
	local last = model:GetAttribute("LastStrike") :: number
	if isArcher then
		if (KEEP_TARGET - root.Position).Magnitude <= ARCHER_STANDOFF then
			if now - last >= ARCHER_COOLDOWN and keepPart then
				model:SetAttribute("LastStrike", now)
				fireArrow(root.Position + Vector3.new(0, 2, 0), keepPart.Position)
				damageKeep(ARCHER_KEEP_DMG)
			end
			return true
		end
		return false
	end
	-- soldier: a defender in reach is struck first; else hack the keep if adjacent
	local pTarget = nearestRoot(root.Position)
	if pTarget and (pTarget.Position - root.Position).Magnitude <= SOLDIER_RANGE then
		if now - last >= SOLDIER_COOLDOWN then
			model:SetAttribute("LastStrike", now)
			local victim = pTarget.Parent and pTarget.Parent:FindFirstChildOfClass("Humanoid")
			if victim then victim:TakeDamage(SOLDIER_DAMAGE) end
		end
		return true
	end
	if (KEEP_TARGET - root.Position).Magnitude <= SOLDIER_RANGE + 6 then
		if now - last >= SOLDIER_COOLDOWN then
			model:SetAttribute("LastStrike", now)
			damageKeep(SOLDIER_KEEP_DMG)
		end
		return true
	end
	return false
end

-- ===== Per-enemy behavior: pathfind to the keep through the gate, then attack =====
local function runEnemy(model: Model)
	local hum = model:FindFirstChildOfClass("Humanoid")
	if not hum then return end
	local isArcher = model:GetAttribute("Kind") == "Archer"
	while enemies[model] and hum.Health > 0 do
		local root = model.PrimaryPart
		if not root or not keepPart then break end

		if attackTick(model, root, isArcher) then
			task.wait(0.3) -- in position: keep striking, don't move
		else
			-- compute a route around the walls to the muster point, walk it, and
			-- break off the moment we come into attack range
			local path = PathfindingService:CreatePath(AGENT_PARAMS)
			local ok = pcall(function() path:ComputeAsync(root.Position, KEEP_TARGET) end)
			if ok and path.Status == Enum.PathStatus.Success then
				local waypoints = path:GetWaypoints()
				for i = 2, #waypoints do
					if not enemies[model] or hum.Health <= 0 then break end
					local r = model.PrimaryPart
					if not r or attackTick(model, r, isArcher) then break end
					hum:MoveTo(waypoints[i].Position)
					hum.MoveToFinished:Wait() -- resolves on arrival or an 8s timeout
				end
			else
				-- no route found this tick: nudge straight at the keep and retry
				hum:MoveTo(KEEP_TARGET)
				hum.MoveToFinished:Wait()
			end
			task.wait(0.1)
		end
	end
end

-- ===== Enemies (built in code: an armored soldier or a leather-clad archer) =====
local function removeEnemy(model: Model)
	if enemies[model] then
		enemies[model] = nil
		enemyCount -= 1
		model:Destroy()
	end
end

local function weld(a: BasePart, b: BasePart)
	local w = Instance.new("WeldConstraint")
	w.Part0, w.Part1 = a, b
	w.Parent = a
end

local function makeEnemy(pos: Vector3, kind: string)
	local isArcher = kind == "Archer"
	local model = Instance.new("Model")
	model.Name = kind

	local torso = Instance.new("Part")
	torso.Name = "HumanoidRootPart"
	torso.Size = Vector3.new(2, 3, 1)
	torso.Color = if isArcher then Color3.fromRGB(70, 90, 55) else Color3.fromRGB(90, 95, 105)
	torso.Material = if isArcher then Enum.Material.Fabric else Enum.Material.Metal
	torso.CFrame = CFrame.new(pos)
	torso.Parent = model
	model.PrimaryPart = torso

	local head = Instance.new("Part")
	head.Name = "Head"
	head.Size = Vector3.new(1.2, 1.2, 1.2)
	head.Color = if isArcher then Color3.fromRGB(120, 100, 70) else Color3.fromRGB(120, 125, 135)
	head.Material = torso.Material
	head.CanCollide = false
	head.CFrame = torso.CFrame * CFrame.new(0, 2.1, 0)
	head.Parent = model
	weld(torso, head)

	if isArcher then
		local bow = Instance.new("Part") -- a simple bow stave
		bow.Name = "Bow"
		bow.Size = Vector3.new(0.2, 3, 0.2)
		bow.Color = Color3.fromRGB(95, 65, 35)
		bow.Material = Enum.Material.Wood
		bow.CanCollide = false
		bow.CFrame = torso.CFrame * CFrame.new(1, 0, -0.6)
		bow.Parent = model
		weld(torso, bow)
	else
		local blade = Instance.new("Part")
		blade.Name = "Blade"
		blade.Size = Vector3.new(0.2, 2.4, 0.2)
		blade.Color = Color3.fromRGB(200, 200, 210)
		blade.Material = Enum.Material.Metal
		blade.CanCollide = false
		blade.CFrame = torso.CFrame * CFrame.new(1.3, 0.4, -0.5)
		blade.Parent = model
		weld(torso, blade)
	end

	local hum = Instance.new("Humanoid")
	hum.MaxHealth = if isArcher then ARCHER_HEALTH else SOLDIER_HEALTH
	hum.Health = hum.MaxHealth
	hum.WalkSpeed = if isArcher then ARCHER_SPEED else SOLDIER_SPEED
	hum.Parent = model

	model:SetAttribute("Kind", kind)
	model:SetAttribute("LastStrike", 0)
	model.Parent = workspace
	enemies[model] = true
	enemyCount += 1

	hum.Died:Connect(function() removeEnemy(model) end)
	task.spawn(runEnemy, model) -- each enemy paths + fights on its own
end

-- ===== Your swing: server checks reach + a forward arc, then strikes =====
SwingSword.OnServerEvent:Connect(function(player)
	if not isAlive(player) then return end
	local char = player.Character
	local root = char and char:FindFirstChild("HumanoidRootPart")
	if not root then return end

	local now = os.clock()
	local last = (player:GetAttribute("LastSwing") or 0) :: number
	if now - last < SWORD_COOLDOWN then return end -- server-side cooldown
	player:SetAttribute("LastSwing", now)

	local origin = root.Position
	local forward = root.CFrame.LookVector
	for model in pairs(enemies) do
		local sroot = model.PrimaryPart
		local hum = model:FindFirstChildOfClass("Humanoid")
		if sroot and hum and hum.Health > 0 then
			local to = sroot.Position - origin
			local dist = to.Magnitude
			if dist > 0.1 and dist <= SWORD_RANGE and forward:Dot(to.Unit) >= SWORD_ARC then
				hum:TakeDamage(SWORD_DAMAGE)
				if hum.Health <= 0 then
					kills[player] = (kills[player] or 0) + 1
					Hud:FireClient(player, { kills = kills[player] })
				end
			end
		end
	end
end)

-- ===== A cosmetic sword, welded into the defender's hand on spawn =====
local function giveSword(char: Model)
	local tool = Instance.new("Tool")
	tool.Name = "Sword"
	tool.RequiresHandle = true
	tool.CanBeDropped = false

	local handle = Instance.new("Part")
	handle.Name = "Handle"
	handle.Size = Vector3.new(0.4, 1.2, 0.4) -- the grip
	handle.Color = Color3.fromRGB(70, 45, 25) -- wrapped leather
	handle.Parent = tool

	local guard = Instance.new("Part")
	guard.Name = "Guard"
	guard.Size = Vector3.new(1.4, 0.25, 0.4)
	guard.Color = Color3.fromRGB(180, 150, 60) -- brass crossguard
	guard.Massless = true
	guard.CanCollide = false
	guard.Parent = tool
	local gw = Instance.new("Weld"); gw.Part0, gw.Part1 = handle, guard; gw.C0 = CFrame.new(0, 0.7, 0); gw.Parent = handle

	local blade = Instance.new("Part")
	blade.Name = "Blade"
	blade.Size = Vector3.new(0.25, 3, 0.25)
	blade.Color = Color3.fromRGB(210, 212, 220)
	blade.Material = Enum.Material.Metal
	blade.Massless = true
	blade.CanCollide = false
	blade.Parent = tool
	local bw = Instance.new("Weld"); bw.Part0, bw.Part1 = handle, blade; bw.C0 = CFrame.new(0, 2.2, 0); bw.Parent = handle

	tool.Parent = char -- parenting a Tool to the character equips it
end

-- ===== Defender lifecycle: fall -> ghost; lose if no defenders remain =====
local function checkDefenders()
	if not running or defeated then return end
	if #Players:GetPlayers() == 0 then return end
	if #alivePlayers() == 0 then
		loseSiege("The defenders have fallen!")
	end
end

Players.PlayerAdded:Connect(function(player)
	kills[player] = 0
	player:SetAttribute("Spectating", false)
	player.CharacterAdded:Connect(function(char)
		local hum = char:WaitForChild("Humanoid") :: Humanoid
		if player:GetAttribute("Spectating") then
			-- ghost look while spectating; the army already ignores via isAlive()
			task.defer(function()
				for _, d in ipairs(char:GetDescendants()) do
					if d:IsA("BasePart") then
						d.Transparency = 0.7
						d.CanCollide = false
					end
				end
				local hl = Instance.new("Highlight")
				hl.FillColor = Color3.fromRGB(150, 160, 255)
				hl.FillTransparency = 0.5
				hl.Parent = char
			end)
		else
			task.defer(function() giveSword(char) end)
		end
		hum.Died:Connect(function()
			if not player:GetAttribute("Spectating") then
				player:SetAttribute("Spectating", true)
				YouDied:FireClient(player)
				checkDefenders()
			end
		end)
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	kills[player] = nil
	checkDefenders()
end)

-- ===== Lose / reset the siege =====
loseSiege = function(msg: string)
	if defeated then return end
	defeated = true
	running = false
	Defeat:FireAllClients(msg, currentWave)
	restartGame()
end

restartGame = function()
	task.wait(4) -- let the defeat banner be read
	for model in pairs(enemies) do removeEnemy(model) end
	currentWave = 0
	buildCastle() -- fresh keep at full health
	Hud:FireAllClients({ wave = 0, keep = keepHealth, keepMax = KEEP_MAX_HP })
	for _, p in ipairs(Players:GetPlayers()) do
		p:SetAttribute("Spectating", false)
		kills[p] = 0
		Hud:FireClient(p, { kills = 0 })
		p:LoadCharacter() -- rally every defender back to the courtyard
	end
	defeated = false
	task.wait(1)
	startGame()
end

-- ===== The siege: growing waves (soldiers + archers) with a pause to regroup =====
local function spawnPoint(): Vector3
	-- a frontal arc off the gate (+Z) face so the army musters before the gate
	local a = math.rad(math.random(-50, 50))
	return CASTLE_ORIGIN + Vector3.new(math.sin(a) * SPAWN_RADIUS, 3, math.cos(a) * SPAWN_RADIUS)
end

startGame = function()
	if running then return end
	running = true
	task.spawn(function()
		while running do
			currentWave += 1
			Hud:FireAllClients({ wave = currentWave, keep = keepHealth, keepMax = KEEP_MAX_HP })
			local soldierN = BASE_SOLDIERS + (currentWave - 1) * PER_WAVE
			local archerN = math.min(MAX_ARCHERS, math.floor(currentWave / 2)) -- archers from Wave II
			for i = 1, soldierN + archerN do
				if not running then break end
				local kind = if i <= archerN then "Archer" else "Soldier"
				makeEnemy(spawnPoint(), kind)
				task.wait(0.25)
			end
			-- hold until the whole wave is cut down
			while running and enemyCount > 0 do task.wait(0.5) end
			if not running then break end
			task.wait(WAVE_PAUSE)
		end
	end)
end

-- Raise the castle, then begin once a defender is present.
buildCastle()
task.spawn(function()
	while #Players:GetPlayers() == 0 do task.wait(1) end
	startGame()
end)
""",
            encoding="utf-8",
        )

        (client_dir / "Client.client.luau").write_text(
            """--!strict
-- Client.client.luau  (StarterPlayerScripts)
-- The defender's screen: a medieval HUD (wave in Roman numerals, foes slain, a
-- CASTLE HEALTH BAR, and a defeat banner) plus click-or-tap to swing. The client
-- only ASKS to swing -- the server checks reach and applies damage, so hits can't
-- be faked. The HUD is built in code, so no imported UI is needed.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")

local player = Players.LocalPlayer
local SwingSword = ReplicatedStorage:WaitForChild("SwingSword")
local Hud        = ReplicatedStorage:WaitForChild("Hud")
local YouDied    = ReplicatedStorage:WaitForChild("YouDied")
local Defeat     = ReplicatedStorage:WaitForChild("Defeat")

-- ===== HUD (built in code) =====
local gui = Instance.new("ScreenGui")
gui.Name = "SiegeHUD"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")

local function makeLabel(pos: UDim2, size: UDim2, parent: Instance): TextLabel
	local l = Instance.new("TextLabel")
	l.BackgroundTransparency = 1
	l.TextColor3 = Color3.fromRGB(235, 225, 200) -- parchment
	l.TextStrokeTransparency = 0.2
	l.Font = Enum.Font.Garamond -- a fittingly old-world serif
	l.TextScaled = true
	l.Position = pos
	l.Size = size
	l.Parent = parent
	return l
end

local waveLabel = makeLabel(UDim2.fromScale(0.02, 0.02), UDim2.fromScale(0.3, 0.07), gui)
waveLabel.TextXAlignment = Enum.TextXAlignment.Left
waveLabel.Text = "Wave I"

local killLabel = makeLabel(UDim2.fromScale(0.02, 0.10), UDim2.fromScale(0.3, 0.05), gui)
killLabel.TextXAlignment = Enum.TextXAlignment.Left
killLabel.Text = "Foes slain: 0"

-- castle health bar, top-centre
local barBg = Instance.new("Frame")
barBg.Name = "CastleBar"
barBg.Size = UDim2.fromScale(0.32, 0.045)
barBg.Position = UDim2.fromScale(0.34, 0.02)
barBg.BackgroundColor3 = Color3.fromRGB(28, 24, 20)
barBg.BorderSizePixel = 0
barBg.Parent = gui
local barFill = Instance.new("Frame")
barFill.Name = "Fill"
barFill.Size = UDim2.fromScale(1, 1)
barFill.BackgroundColor3 = Color3.fromRGB(90, 170, 80)
barFill.BorderSizePixel = 0
barFill.Parent = barBg
local barText = makeLabel(UDim2.fromScale(0, 0), UDim2.fromScale(1, 1), barBg)
barText.Text = "Castle"
barText.ZIndex = 2

local banner = makeLabel(UDim2.fromScale(0.15, 0.4), UDim2.fromScale(0.7, 0.16), gui)
banner.TextColor3 = Color3.fromRGB(200, 60, 50)
banner.Text = ""

local ROMAN = {
	{1000,"M"},{900,"CM"},{500,"D"},{400,"CD"},{100,"C"},{90,"XC"},
	{50,"L"},{40,"XL"},{10,"X"},{9,"IX"},{5,"V"},{4,"IV"},{1,"I"},
}
local function toRoman(n: number): string
	local out = ""
	for _, pair in ipairs(ROMAN) do
		while n >= pair[1] do
			out ..= pair[2]
			n -= pair[1]
		end
	end
	return if out ~= "" then out else "I"
end

Hud.OnClientEvent:Connect(function(data)
	if type(data) ~= "table" then return end
	if data.wave and data.wave > 0 then
		waveLabel.Text = "Wave " .. toRoman(data.wave)
		banner.Text = "" -- clear the defeat banner when a fresh siege begins
	end
	if data.kills then killLabel.Text = "Foes slain: " .. tostring(data.kills) end
	if data.keep then
		local maxHp = data.keepMax or 500
		local frac = math.clamp(data.keep / maxHp, 0, 1)
		barFill.Size = UDim2.fromScale(frac, 1)
		-- green -> red as the keep crumbles
		barFill.BackgroundColor3 = Color3.fromRGB(math.floor(200 - frac * 110), math.floor(60 + frac * 110), 70)
		barText.Text = "Castle  " .. tostring(data.keep) .. " / " .. tostring(maxHp)
	end
end)

YouDied.OnClientEvent:Connect(function()
	banner.TextColor3 = Color3.fromRGB(200, 60, 50)
	banner.Text = "You have fallen"
end)

Defeat.OnClientEvent:Connect(function(msg, wavesHeld)
	banner.TextColor3 = Color3.fromRGB(200, 60, 50)
	banner.Text = tostring(msg) .. "  (held " .. tostring(wavesHeld) .. " waves)"
	task.delay(4, function()
		if banner.Text ~= "" then banner.Text = "" end
	end)
end)

-- ===== Swing: click / tap =====
local COOLDOWN = 0.6
local lastSwing = 0.0

UserInputService.InputBegan:Connect(function(input, processed)
	if processed then return end
	if input.UserInputType ~= Enum.UserInputType.MouseButton1
		and input.UserInputType ~= Enum.UserInputType.Touch then
		return
	end
	if player:GetAttribute("Spectating") then return end -- ghosts don't fight
	local now = os.clock()
	if now - lastSwing < COOLDOWN then return end
	lastSwing = now

	SwingSword:FireServer()

	-- a small local flourish: flash the blade white for the swing
	local char = player.Character
	local tool = char and char:FindFirstChild("Sword")
	local blade = tool and tool:FindFirstChild("Blade") :: BasePart?
	if blade then
		local original = blade.Color
		blade.Color = Color3.fromRGB(255, 255, 255)
		task.delay(0.1, function()
			if blade and blade.Parent then blade.Color = original end
		end)
	end
end)
""",
            encoding="utf-8",
        )

        (shared_dir / ".gitkeep").write_text(
            "-- Remotes (SwingSword, Hud, YouDied, Defeat) are created at runtime by\n"
            "-- GameServer.server.luau, so no shared modules are needed for this game.\n",
            encoding="utf-8",
        )

        (project_dir / "README.md").write_text(
            f"""# {project_name} -- a wave-survival castle defense

Defend the **castle keep** against an invading army that **paths in through the
gate**. A fully-walled stone castle with a single **gatehouse** is raised in code;
melee **soldiers** and ranged **archers** use Roblox `PathfindingService` to route
around the walls, funnel through the gate, and assault the keep. Cut them down with
your **sword** before the keep's health hits zero. It's the Roblox *Wave Survival*
pattern re-themed to a siege and built to the same reference standard: **Script
Sync** layout, **server-authoritative** design (the server owns the enemies, all
pathing and damage, the keep's health, waves and the lose-state), and **everything
built in code** -- the castle, the enemies, the sword and the HUD -- so it runs
with no imported assets.

## What happens

- A stone **castle** with four walls, a **gate** and a central **keep** is raised
  in code. Defenders spawn in the courtyard.
- Each wave, an army musters beyond the gate: **soldiers** (melee) plus **archers**
  (from Wave II on). They **pathfind around the walls and through the gate** to
  reach the keep -- so the gate is a real choke point to hold.
- **Soldiers** hack the keep -- or any defender who blocks the gate. **Archers**
  hold at range and volley arrows over the wall; sortie out to cut them down.
- Your **sword** fells a soldier in **three hits**, an archer in **two** --
  click/tap to swing. The server checks reach + a forward arc, so hits can't be
  faked by the client.
- **You lose** when the **keep's health reaches zero** or **every defender has
  fallen** -- then the siege **resets at Wave I**. Your score is the number of
  **waves you hold**.
- HUD: **wave in Roman numerals**, **foes slain**, a **castle health bar**
  (green -> red as it crumbles), and a defeat banner. Each defender spawns holding
  a sword.

## Files (Script Sync layout)

- `ServerScriptService/GameServer.server.luau` -- the whole server: the walled
  castle + gate + keep health, waves, soldier/archer **pathfinding AI**, arrows,
  your sword hit-detection, spectator mode, lose/reset. Creates the RemoteEvents.
- `StarterPlayerScripts/Client.client.luau` -- HUD (incl. the castle bar) +
  click-to-swing + blade flash.

## Run it

1. In Studio: **File -> Beta Features -> Script Sync**, enable it, restart.
2. Right-click **ServerScriptService -> Script Sync -> Sync to** and pick the
   `{project_name}` folder (not the subfolders -- the names already match).
   Repeat for **StarterPlayerScripts**.
3. The two scripts appear in Studio. Press **Play** -- the army paths in through
   the gate and assaults the keep.

> Note: if your place still has the baseplate's default `SpawnLocation`, delete it
> so defenders always spawn at the castle's `DefenderSpawn`.

## Tune the battle

All the knobs live at the top of `GameServer.server.luau`: `KEEP_MAX_HP`,
`SOLDIER_KEEP_DMG` / `ARCHER_KEEP_DMG`, `SOLDIER_HEALTH` / `ARCHER_HEALTH`,
`ARCHER_STANDOFF`, `SWORD_RANGE` / `SWORD_ARC`, `BASE_SOLDIERS` / `PER_WAVE` /
`MAX_ARCHERS`, `WAVE_PAUSE`, plus `AGENT_PARAMS` (how the pathfinder sizes an enemy)
and the gate width inside `buildCastle`.

> Security: the server never trusts the client. Damage, health, the keep, waves
> and the lose-state all live on the server. Docs:
> https://create.roblox.com/docs/scripting/security/client-server-boundary
""",
            encoding="utf-8",
        )

        return {
            "action": "wave_survival",
            "theme": "medieval",
            "engine": "roblox",
            "project_dir": str(project_dir),
            "files_created": [
                "ServerScriptService/GameServer.server.luau",
                "StarterPlayerScripts/Client.client.luau",
                "ReplicatedStorage/.gitkeep",
                "README.md",
            ],
            "next_step": (
                "In Roblox Studio enable Script Sync (File > Beta Features), then "
                "Sync ServerScriptService and StarterPlayerScripts to this folder and press Play."
            ),
        }
