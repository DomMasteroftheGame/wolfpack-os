package com.wolfpack.carseat

import android.os.Handler
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.Action
import androidx.car.app.model.CarColor
import androidx.car.app.model.Pane
import androidx.car.app.model.PaneTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template
import androidx.car.app.CarToast
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * One approval with Approve / Deny actions (2 actions = the driving-state max).
 * Decisions POST through the phone dashboard, which injects the mesh token.
 */
class ApprovalDetailScreen(carContext: CarContext, private val approval: Approval) :
    Screen(carContext), DefaultLifecycleObserver {

    @Volatile
    private var busy = false
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    init {
        lifecycle.addObserver(this)
    }

    override fun onDestroy(owner: LifecycleOwner) {
        scope.cancel()
    }

    override fun onGetTemplate(): Template {
        val pane = Pane.Builder()
        pane.addRow(
            Row.Builder()
                .setTitle(approval.action.ifEmpty { "(no action)" })
                .addText(ellipsis(approval.detail.ifEmpty { "no detail given" }, 180))
                .build()
        )
        pane.addRow(
            Row.Builder()
                .setTitle("From ${approval.from}")
                .addText("risk ${approval.risk} · ${age(approval.ts)}" +
                    (approval.expiresTs?.let { " · expires $it" } ?: ""))
                .build()
        )
        // Pane is capped at 4 rows while driving; items beyond 2 are summarized.
        approval.items.take(2).forEach { item ->
            pane.addRow(Row.Builder().setTitle("• ${ellipsis(item.label, 40)}").addText(item.status).build())
        }
        if (approval.items.size > 2) {
            pane.addRow(Row.Builder().setTitle("…").addText("+${approval.items.size - 2} more line items — decision applies to the whole approval").build())
        }
        pane.addAction(
            Action.Builder()
                .setTitle(if (busy) "Working…" else "Approve")
                .setBackgroundColor(CarColor.GREEN)
                .setOnClickListener { decide("approve") }
                .build()
        )
        pane.addAction(
            Action.Builder()
                .setTitle("Deny")
                .setBackgroundColor(CarColor.RED)
                .setOnClickListener { decide("deny") }
                .build()
        )
        return PaneTemplate.Builder(pane.build())
            .setTitle("Approval")
            .setHeaderAction(Action.BACK)
            .build()
    }

    private fun decide(decision: String) {
        if (busy) return
        busy = true
        scope.launch {
            val err = try {
                Api.decide(approval.id, decision)
            } catch (e: Exception) {
                e.message ?: "request failed"
            }
            Handler(carContext.mainLooper).post {
                busy = false
                if (err == null) {
                    CarToast.makeText(carContext, "${decision}d: ${ellipsis(approval.action, 40)}", CarToast.LENGTH_LONG).show()
                    screenManager.pop()
                } else {
                    CarToast.makeText(carContext, "Failed: ${ellipsis(err, 60)}", CarToast.LENGTH_LONG).show()
                }
            }
        }
    }
}
