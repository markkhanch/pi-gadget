def read_buttons(hw, prev_states):
    pins = hw.pins
    new_states = {}
    event = None

    # First check virtual buttons from the browser
    remote_event = hw.pop_remote_event()
    if remote_event:
        # Copy prev_states unchanged (physical buttons were not touched)
        for name, pin in pins.items():
            new_states[name] = prev_states.get(name, 1)
        return remote_event, new_states

    # Read physical GPIO buttons as usual
    for name, pin in pins.items():
        val = hw.gpio_read(pin)
        new_states[name] = val
        prev = prev_states.get(name, 1)
        if prev == 1 and val == 0 and event is None:
            event = name

    return event, new_states