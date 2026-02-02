def read_buttons(hw, prev_states):
    pins = hw.pins
    new_states = {}
    event = None

    for name, pin in pins.items():
        val = hw.gpio_read(pin)
        new_states[name] = val
        prev = prev_states.get(name, 1)
        if prev == 1 and val == 0 and event is None:
            event = name

    return event, new_states
