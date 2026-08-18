package com.wolfpack.carseat

import android.content.Intent
import androidx.car.app.Screen
import androidx.car.app.Session

class WolfSession : Session() {
    override fun onCreateScreen(intent: Intent): Screen = MainScreen(carContext)
}
