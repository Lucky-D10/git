"""Tk display adapter. All session calculations and output belong to backend."""
if __name__ == "__main__":
    import sys
    from app import main
    raise SystemExit(main(["racing", *sys.argv[1:]]))

from backend.ui import SessionPanel


class FocusRacingGame(SessionPanel):
    def __init__(self, root, backend=None):
        super().__init__(root, backend, "racing")
