package com.wolfpack.carseat

import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template

/** Home: pending approvals, mesh health, wolf activity, and Dom's queue. */
class MainScreen(carContext: CarContext) : PollScreen<SeatSnapshot>(carContext) {

    override fun fetch(): SeatSnapshot = Api.snapshot()

    override fun onGetTemplate(): Template {
        val snap = data
        val list = ItemList.Builder()
        when {
            snap == null && error == null ->
                list.addItem(plainRow("Waking the seat…", "polling the dashboard at 127.0.0.1:8787"))

            snap == null -> {
                list.addItem(plainRow("Seat unreachable", ellipsis(error ?: "unknown error", 80)))
                list.addItem(plainRow("Is the seat running?", "start-all.sh in the proot — see car-seat/README.md"))
            }

            else -> {
                val pending = snap.approvals
                val top = pending.maxByOrNull { riskRank(it.risk) }
                list.addItem(
                    Row.Builder()
                        .setTitle("Approvals")
                        .addText(
                            if (pending.isEmpty()) "none pending"
                            else "${pending.size} pending · top risk ${top?.risk?.uppercase() ?: "?"}"
                        )
                        .setOnClickListener { screenManager.push(ApprovalsScreen(carContext)) }
                        .build()
                )

                val up = snap.peers.count { it.alive }
                list.addItem(
                    Row.Builder()
                        .setTitle("Mesh hubs")
                        .addText("$up/${snap.peers.size} up · leader ${snap.leaderId}")
                        .setOnClickListener { screenManager.push(HubsScreen(carContext)) }
                        .build()
                )

                val busy = snap.wolves.count { it.status != "idle" }
                list.addItem(
                    Row.Builder()
                        .setTitle("Wolves")
                        .addText(if (busy == 0) "all ${snap.wolves.size} idle" else "$busy busy · ${snap.wolves.size - busy} idle")
                        .setOnClickListener { screenManager.push(AgentsScreen(carContext)) }
                        .build()
                )

                list.addItem(
                    plainRow(
                        "For you: ${snap.human.count} task${if (snap.human.count == 1) "" else "s"}",
                        snap.human.latest?.let { ellipsis(it, 80) } ?: "nothing addressed to Dom"
                    )
                )
            }
        }
        return ListTemplate.Builder()
            .setTitle("Wolfpack Seat")
            .setHeaderAction(
                Action.Builder()
                    .setTitle("Refresh")
                    .setOnClickListener { kick() }
                    .build()
            )
            .setSingleList(list.build())
            .build()
    }

    private fun plainRow(title: String, text: String): Row =
        Row.Builder().setTitle(title).addText(text).build()
}
