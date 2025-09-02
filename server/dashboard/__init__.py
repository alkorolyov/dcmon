"""
dcmon Dashboard Module

AI-friendly dashboard with uPlot time series charts and minimal JavaScript.
All dashboard logic is contained in pure Python for easy debugging and maintenance.
"""

from .controller import DashboardController

__all__ = ["DashboardController"]