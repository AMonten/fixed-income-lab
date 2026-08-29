"""fixed-income-lab: a fixed-income analytics toolkit.

See the top-level README for methodology, supported instruments, and
worked examples. :mod:`fixed_income.analytics` (``SecurityAnalytics``,
``analyze_bond``, ``analyze_cash_flows``) is the primary entry point for
end-to-end price/yield/risk analysis of a single security.
"""

from .analytics import SecurityAnalytics, analyze_bond, analyze_cash_flows

__version__ = "0.1.0"

__all__ = ["SecurityAnalytics", "analyze_bond", "analyze_cash_flows", "__version__"]
