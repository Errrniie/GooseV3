"""
Main.py - Jetson entry point.

This simply runs the main application logic without any local GUI;
the control GUI will live on the laptop side and talk over the network.
"""

import main_app


if __name__ == "__main__":
    main_app.run()