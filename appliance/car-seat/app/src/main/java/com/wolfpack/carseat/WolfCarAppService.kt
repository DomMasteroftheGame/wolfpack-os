package com.wolfpack.carseat

import androidx.car.app.CarAppService
import androidx.car.app.Session
import androidx.car.app.validation.HostValidator

class WolfCarAppService : CarAppService() {
    // Sideload-only personal app — no Play distribution, so no host allowlist.
    override fun createHostValidator(): HostValidator = HostValidator.ALLOW_ALL_HOSTS_VALIDATOR

    override fun onCreateSession(): Session = WolfSession()
}
