package com.wolfpack.carseat

import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template

/** The seven wolves and what each is doing right now. */
class AgentsScreen(carContext: CarContext) : PollScreen<List<Wolf>>(carContext) {

    override fun fetch(): List<Wolf> = Api.wolves()

    override fun onGetTemplate(): Template {
        val wolves = data
        val list = ItemList.Builder()
        when {
            wolves == null && error == null ->
                list.addItem(plainRow("Loading…", "asking the leader hub"))

            wolves == null ->
                list.addItem(plainRow("Leader unreachable", ellipsis(error ?: "unknown error", 80)))

            wolves.isEmpty() ->
                list.addItem(plainRow("No wolves reported", "is the leader hub initialized?"))

            else -> {
                wolves.take(5).forEach { w ->
                    list.addItem(
                        plainRow(
                            "${w.name} · ${w.id}",
                            w.currentTask?.let { "${w.status} — ${ellipsis(it, 60)}" } ?: "${w.status} · ${w.role}"
                        )
                    )
                }
                if (wolves.size > 5) {
                    list.addItem(plainRow("…and ${wolves.size - 5} more", "tactical board is on the phone dashboard"))
                }
            }
        }
        return ListTemplate.Builder()
            .setTitle("Wolves")
            .setHeaderAction(Action.BACK)
            .setSingleList(list.build())
            .build()
    }

    private fun plainRow(title: String, text: String): Row =
        Row.Builder().setTitle(title).addText(text).build()
}
