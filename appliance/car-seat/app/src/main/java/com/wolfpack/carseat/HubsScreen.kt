package com.wolfpack.carseat

import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template

/** Hub mesh health from the leader's point of view (via the phone dashboard). */
class HubsScreen(carContext: CarContext) : PollScreen<Pair<String, List<HubPeer>>>(carContext) {

    override fun fetch(): Pair<String, List<HubPeer>> = Api.mesh()

    override fun onGetTemplate(): Template {
        val mesh = data
        val list = ItemList.Builder()
        when {
            mesh == null && error == null ->
                list.addItem(plainRow("Loading…", "asking the leader hub"))

            mesh == null ->
                list.addItem(plainRow("Leader unreachable", ellipsis(error ?: "unknown error", 80)))

            mesh.second.isEmpty() ->
                list.addItem(plainRow("No peers reported", "leader ${mesh.first} sees an empty mesh"))

            else -> {
                mesh.second.take(5).forEach { p ->
                    list.addItem(
                        plainRow(
                            (if (p.isLeader) "★ " else "") + p.hubId,
                            if (p.alive) "up · ${p.url}"
                            else "DOWN — ${ellipsis(p.lastError ?: "no heartbeat", 60)}"
                        )
                    )
                }
                if (mesh.second.size > 5) {
                    list.addItem(plainRow("…and ${mesh.second.size - 5} more", "check-hubs.sh on the phone for the full sweep"))
                }
            }
        }
        return ListTemplate.Builder()
            .setTitle("Mesh hubs")
            .setHeaderAction(Action.BACK)
            .setSingleList(list.build())
            .build()
    }

    private fun plainRow(title: String, text: String): Row =
        Row.Builder().setTitle(title).addText(text).build()
}
