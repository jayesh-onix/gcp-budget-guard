"""Objects related to Project Budget / Expense / Expense Limit."""

import os
from dataclasses import dataclass

from helpers.constants import GCP_LOGGER


@dataclass
class ExpenseLimit:
    """Expense Limit in dollars ($)."""

    daily: int = int(os.environ.get("DAILY_EXPENSE_LIMIT", default=100))
    weekly: int = int(os.environ.get("WEEKLY_EXPENSE_LIMIT", default=500))
    monthly: int = int(os.environ.get("MONTHLY_EXPENSE_LIMIT", default=1000))


@dataclass
class CurrentExpense:
    """Current Budget of your project in dollars ($)."""

    daily: float = 0
    weekly: float = 0
    monthly: float = 0


class ProjectBudget:
    """Whole Project Object that follow the limit vs the expense and check them."""

    def __init__(self) -> None:
        self.expense_limit = ExpenseLimit()
        self.current_expense = CurrentExpense()

    def check_expense_limit(self) -> bool:
        """Check the actual expense daily / weekly / monthly against the limit daily / weekly / monthly."""
        if self.current_expense.daily >= self.expense_limit.daily:
            GCP_LOGGER.warning(
                msg=f"Daily expense limit reached: {self.current_expense.daily} - Limit was: {self.expense_limit.daily}"
            )
        elif self.current_expense.weekly >= self.expense_limit.weekly:
            GCP_LOGGER.warning(
                msg=f"Weekly expense limit reached: {self.current_expense.weekly} - Limit was: {self.expense_limit.weekly}"
            )
        elif self.current_expense.monthly >= self.expense_limit.monthly:
            GCP_LOGGER.warning(
                msg=f"Monthly expense limit reached: {self.current_expense.monthly} - Limit was: {self.expense_limit.monthly}"
            )
        else:
            GCP_LOGGER.info(msg="Expense limit not reached")
            return False
        return True
