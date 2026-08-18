package com.wolfpack.carseat

import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class SeatException(msg: String) : Exception(msg)

data class ApprovalItem(val id: String, val label: String, val status: String)

data class Approval(
    val id: String,
    val ts: String,
    val from: String,
    val action: String,
    val detail: String,
    val risk: String,
    val status: String,
    val expiresTs: String?,
    val items: List<ApprovalItem>,
)

data class HubPeer(val hubId: String, val url: String, val alive: Boolean, val lastError: String?, val isLeader: Boolean)

data class Wolf(val id: String, val name: String, val role: String, val status: String, val currentTask: String?)

data class HumanQueue(val count: Int, val latest: String?)

data class SeatSnapshot(
    val approvals: List<Approval>,
    val leaderId: String,
    val peers: List<HubPeer>,
    val wolves: List<Wolf>,
    val human: HumanQueue,
)

/**
 * Client for the phone-seat dashboard (Termux proot, 127.0.0.1:8787).
 *
 * The dashboard proxies the leader hub and injects the mesh token server-side,
 * so this app holds no credentials. Envelope shapes, from dashboard/server.mjs:
 *   /api/approvals          -> {ok, status, json:{ok, count, approvals:[...]}}
 *   /api/approvals/:id/decision (POST) -> {ok, status, json:{ok:true,...}}
 *   /api/status             -> {leader:{ok,status,json:{leaderId, peers:[...]}},
 *                               agents:{ok,status,json:[wolf,...]}}
 *   /api/human              -> {ok, count, tasks:[{ts, from, text, priority}]}  (no envelope)
 */
object Api {
    private const val BASE = "http://127.0.0.1:8787"
    private const val CONNECT_MS = 6_000
    private const val READ_MS = 20_000 // dashboard fans out to the leader over the tailnet

    fun approvals(): List<Approval> {
        val json = unwrap(get("/api/approvals"))
        val arr = json.optJSONArray("approvals") ?: return emptyList()
        return List(arr.length()) { i -> parseApproval(arr.getJSONObject(i)) }
    }

    fun mesh(): Pair<String, List<HubPeer>> {
        val leader = unwrap(get("/api/status").getJSONObject("leader"))
        val leaderId = leader.optString("leaderId", "?")
        val arr = leader.optJSONArray("peers") ?: return leaderId to emptyList()
        val peers = List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            HubPeer(
                hubId = o.optString("hubId"),
                url = o.optString("url"),
                alive = o.optBoolean("alive"),
                lastError = if (o.isNull("lastError")) null else o.optString("lastError"),
                isLeader = o.optString("hubId") == leaderId,
            )
        }
        return leaderId to peers
    }

    fun wolves(): List<Wolf> {
        val agents = get("/api/status").getJSONObject("agents")
        if (!agents.optBoolean("ok")) throw SeatException(agents.optString("error").ifEmpty { "agents unreachable" })
        val arr = agents.getJSONArray("json")
        return List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            val task = o.optJSONObject("currentTask")?.optString("title")?.takeIf { it.isNotEmpty() }
                ?: if (o.isNull("currentTask")) null else o.opt("currentTask")?.toString()
            Wolf(
                id = o.optString("id"),
                name = o.optString("name"),
                role = o.optString("role"),
                status = o.optString("status", "unknown"),
                currentTask = task,
            )
        }
    }

    fun human(): HumanQueue {
        val root = get("/api/human")
        val arr = root.optJSONArray("tasks") ?: return HumanQueue(0, null)
        val latest = if (arr.length() > 0) arr.getJSONObject(0).optString("text").takeIf { it.isNotEmpty() } else null
        return HumanQueue(root.optInt("count", arr.length()), latest)
    }

    fun snapshot(): SeatSnapshot {
        val approvals = approvals()
        val (leaderId, peers) = mesh()
        return SeatSnapshot(approvals, leaderId, peers, wolves(), human())
    }

    /** @return null on success, otherwise a human-readable error. */
    fun decide(id: String, decision: String): String? {
        val body = JSONObject().put("decision", decision).put("note", "via car-seat").toString()
        val root = post("/api/approvals/${URLEncoder.encode(id, "UTF-8")}/decision", body)
        val json = root.optJSONObject("json")
        return if (root.optBoolean("ok") && (json == null || json.optBoolean("ok", true))) {
            null
        } else {
            json?.optString("error")?.takeIf { it.isNotEmpty() }
                ?: root.optString("error").takeIf { it.isNotEmpty() }
                ?: "decision rejected (status ${root.optInt("status")})"
        }
    }

    // --- plumbing -----------------------------------------------------------

    /** The dashboard wraps proxied hub calls as {ok, status, json:<payload>}. */
    private fun unwrap(root: JSONObject): JSONObject {
        if (!root.optBoolean("ok")) throw SeatException(root.optString("error").ifEmpty { "hub unreachable" })
        return root.optJSONObject("json") ?: throw SeatException("empty hub payload")
    }

    private fun parseApproval(o: JSONObject): Approval {
        val itemsArr = o.optJSONArray("items")
        val items = if (itemsArr == null) emptyList() else List(itemsArr.length()) { j ->
            val it = itemsArr.getJSONObject(j)
            ApprovalItem(it.optString("id"), it.optString("label"), it.optString("status"))
        }
        return Approval(
            id = o.optString("id"),
            ts = o.optString("ts"),
            from = o.optString("from"),
            action = o.optString("action"),
            detail = o.optString("detail"),
            risk = o.optString("risk", "medium"),
            status = o.optString("status", "pending"),
            expiresTs = o.optString("expiresTs").takeIf { it.isNotEmpty() && it != "null" },
            items = items,
        )
    }

    private fun get(path: String): JSONObject = request("GET", path, null)

    private fun post(path: String, body: String): JSONObject = request("POST", path, body)

    private fun request(method: String, path: String, body: String?): JSONObject {
        val conn = (URL(BASE + path).openConnection() as HttpURLConnection).apply {
            connectTimeout = CONNECT_MS
            readTimeout = READ_MS
            requestMethod = method
            if (body != null) {
                doOutput = true
                setRequestProperty("content-type", "application/json")
            }
        }
        try {
            if (body != null) OutputStreamWriter(conn.outputStream).use { it.write(body) }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.readText().orEmpty()
            if (code !in 200..299) throw SeatException("dashboard HTTP $code — is the seat running?")
            return JSONObject(text.ifEmpty { "{}" })
        } finally {
            conn.disconnect()
        }
    }
}
