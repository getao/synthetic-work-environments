"""Multi-agent pipeline package.

Three serial modules:
  1. cold_start   — Steps 1-5: persona profile + PC filesystem generation
  2. task_planning — Step 6 + 6.5: monthly KPIs, deliverables, external NPCs
  3. daily_execution — Steps 7-9: weekly planning, daily work, evaluation
"""

from agents.cold_start import cold_start
from agents.task_planning import run_task_planning
from agents.daily_execution import daily_simulate
