package com.wolfpack.carseat

import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template

/** Pending human approvals, newest first. Tap one to decide. */
class ApprovalsScreen(carContext: CarContext) : PollScreen<List<Approval>>(carContext) {

    override fun fetch(): List<Approval> = Api.approvals()

    override fun onGetTemplate(): Template {
        val approvals = data
        val list = ItemList.Builder()
        when {
            approvals == null && error == null ->
                list.addItem(plainRow("Loading…", "asking the leader hub"))

            approvals == null ->
                list.addItem(plainRow("Leader unreachable", ellipsis(error ?: "unknown error", 80)))

            approvals.isEmpty() ->
                list.addItem(plainRow("No pending approvals", "the pack is quiet"))

            else -> {
                // Driving-state lists are capped at 6 rows; keep one for overflow note.
                approvals.take(5).forEach { a ->
                    list.addItem(
                        Row.Builder()
                            .setTitle(ellipsis(a.action.ifEmpty { "(no action)" }, 48))
                            .addText("${a.from} · risk ${a.risk} · ${age(a.ts)}" +
                                (a.expiresTs?.let { " · expires $it" } ?: ""))
                            .setOnClickListener { screenManager.push(ApprovalDetailScreen(carContext, a)) }
                            .build()
                    )
                }
                if (approvals.size > 5) {
                    list.addItem(plainRow("…and ${approvals.size - 5} more", "use the phone dashboard for the full queue"))
                }
            }
        }
        return ListTemplate.Builder()
            .setTitle("Approvals")
            .setHeaderAction(Action.BACK)
            .setSingleList(list.build())
            .build()
    }

    private fun plainRow(title: String, text: String): Row =
        Row.Builder().setTitle(title).addText(text).build()
}
