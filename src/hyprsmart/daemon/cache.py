import time
from dataclasses import dataclass
from threading import Lock

from hyprsmart.primitive import Window


@dataclass
class WinEntry:
    text_l: float
    bg_l: float
    title: str
    time_set: float

WIN_CACHE: dict[str, WinEntry] = {}
CACHE_LOCK = Lock()
MAX_AGE = 30

def cache_get(win: Window)-> None | WinEntry:
    with CACHE_LOCK:
        e = WIN_CACHE.get(win.address)
    if e and e.title == win.title and time.time() - e.time_set < MAX_AGE:
        return e
    return None

def cache_put(win: Window, text_l: int, bg_l: int)-> None:
    with CACHE_LOCK:
        WIN_CACHE[win.address] = WinEntry(
            text_l, 
            bg_l, 
            win.title, 
            time.time()
        )

def cache_drop(address: str)-> None:
    with CACHE_LOCK:
        WIN_CACHE.pop(address, None)