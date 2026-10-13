from hyprsmart.daemon import (
    listen_hyprland_socket,
    load_hyprsmart_daemons,
    handle_event
)

def main() -> None:
    load_hyprsmart_daemons()
    listen_hyprland_socket(handle_event)
