from daemon import handle_event, load_hyprsmart_daemons
from hyprsmart import listen_hyprland_socket


def main() -> None:
    load_hyprsmart_daemons()
    listen_hyprland_socket(handle_event)