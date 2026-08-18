package com.wolfpack.carseat

import java.time.Duration
import java.time.Instant

/** "3m ago" style rendering of an ISO-8601 timestamp; falls back to the raw head. */
fun age(ts: String?): String {
    if (ts.isNullOrEmpty()) return "?"
    return try {
        val d = Duration.between(Instant.parse(ts), Instant.now())
        when {
            d.isNegative -> "just now"
            d.toMinutes() < 1 -> "just now"
            d.toHours() < 1 -> "${d.toMinutes()}m ago"
            d.toDays() < 1 -> "${d.toHours()}h ago"
            else -> "${d.toDays()}d ago"
        }
    } catch (e: Exception) {
        ts.take(16)
    }
}

fun ellipsis(s: String, n: Int): String = if (s.length <= n) s else s.take(n - 1).trimEnd() + "…"

fun riskRank(risk: String): Int = when (risk.lowercase()) {
    "high" -> 3
    "medium" -> 2
    else -> 1
}
