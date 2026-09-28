"""The only backend -> motor bridge; 20ms GPIO watchdog is independent of service/UI."""
class MotorOutput:
    def __init__(self, eeg, config):
        self.eeg, self.config = eeg, config
        self.armed = False

    def __call__(self, state):
        eeg = self.eeg
        with eeg.motor_lock:
            eeg._control_bindings = tuple(state.get("bindings", (1, 2)))
            if state["state"] != "running" or state["safety"] != "allowed":
                eeg.enable_motors(False)
                self.armed = False
                return None
            if self.armed and not eeg.controller.enabled:
                return eeg.controller.reason or "motor_watchdog_locked"
            if eeg._gpio_fault:
                return "gpio_fault_locked"
            if not self.armed:
                if not eeg.enable_motors(True):
                    return "motor_not_ready"
                self.armed = True
            speeds = [p["power"] * self.config.max_race_speed for p in state["players"]]
            speeds += [0.0] * (2-len(speeds))
            eeg.set_race_speeds(*speeds)
        return None
