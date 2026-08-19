package com.wolfpack.carseat

import android.os.Handler
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * A screen that re-polls the phone-seat dashboard while it is visible
 * (dashboard state changes as wolves work — polling keeps the head unit honest).
 */
abstract class PollScreen<T>(carContext: CarContext, private val periodMs: Long = 15_000) :
    Screen(carContext), DefaultLifecycleObserver {

    @Volatile
    protected var data: T? = null

    @Volatile
    protected var error: String? = null

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    @Throws(Exception::class)
    protected abstract fun fetch(): T

    init {
        lifecycle.addObserver(this)
    }

    override fun onStart(owner: LifecycleOwner) = kick()

    override fun onStop(owner: LifecycleOwner) {
        job?.cancel()
    }

    override fun onDestroy(owner: LifecycleOwner) {
        scope.cancel()
    }

    /** (Re)start polling now. */
    fun kick() {
        job?.cancel()
        job = scope.launch {
            while (isActive) {
                try {
                    data = fetch()
                    error = null
                } catch (e: Exception) {
                    error = e.message ?: "fetch failed"
                }
                Handler(carContext.mainLooper).post { invalidate() }
                delay(periodMs)
            }
        }
    }
}
