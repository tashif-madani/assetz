from odoo import fields, models
from odoo.exceptions import ValidationError


class AssetzTaskTimeWizard(models.TransientModel):
    """Picks a Start or End time for a job task with chronology checks.

    Opens when the user clicks the inline Start / End button on the
    Tasks tab of an Assetz job. Validates:
      - time is not in the future
      - Start can't be earlier than the most-recent already-ended task
        in the same job (chronology)
      - End must be after Start
    """

    _name = "assetz.task.time.wizard"
    _description = "Assetz Task Time Picker"

    task_id = fields.Many2one(
        "project.task",
        string="Task",
        required=True,
        readonly=True,
    )
    action_type = fields.Selection(
        selection=[("start", "Start"), ("end", "End")],
        required=True,
        readonly=True,
    )
    datetime = fields.Datetime(
        string="Time",
        required=True,
        default=fields.Datetime.now,
    )

    def action_apply(self):
        self.ensure_one()
        dt = self.datetime
        now = fields.Datetime.now()
        if dt > now:
            raise ValidationError("Time cannot be in the future.")

        task = self.task_id
        if self.action_type == "start":
            # Arrive-first gate: nothing else can be started until
            # "Arrive at Location" is completed.
            if not task.assetz_is_arrival:
                arrival = self.env["project.task"].search(
                    [
                        ("parent_id", "=", task.parent_id.id),
                        ("assetz_is_arrival", "=", True),
                    ],
                    limit=1,
                )
                if arrival and arrival.assetz_task_status != "done":
                    raise ValidationError(
                        "Please complete 'Arrive at Location' before starting "
                        "any other task."
                    )
            # Chronology check: any earlier task (lower sequence) that
            # already has an end time — this one's start must be ≥ that.
            prev_done = self.env["project.task"].search(
                [
                    ("parent_id", "=", task.parent_id.id),
                    ("sequence", "<", task.sequence),
                    ("display_type", "!=", "line_section"),
                    ("assetz_task_end_dt", "!=", False),
                ],
                order="assetz_task_end_dt desc",
                limit=1,
            )
            if prev_done and dt < prev_done.assetz_task_end_dt:
                raise ValidationError(
                    "Start time can't be earlier than the previous task's "
                    f"end time ({prev_done.name} ended at "
                    f"{prev_done.assetz_task_end_dt:%Y-%m-%d %H:%M})."
                )
            # Arrive / Leave Location are instants — picking Start
            # auto-stamps End to the same moment and marks the task Done
            # in one click. Other tasks behave normally (status → in_progress).
            if task.assetz_is_arrival or task.assetz_is_departure:
                task.write({
                    "assetz_task_start_dt": dt,
                    "assetz_task_end_dt": dt,
                    "assetz_task_status": "done",
                })
            else:
                task.write({
                    "assetz_task_start_dt": dt,
                    "assetz_task_status": "in_progress",
                })
        else:  # end
            if task.assetz_task_start_dt and dt < task.assetz_task_start_dt:
                raise ValidationError(
                    "End time must be on or after the Start time "
                    f"({task.assetz_task_start_dt:%Y-%m-%d %H:%M})."
                )
            task.write({
                "assetz_task_end_dt": dt,
                "assetz_task_status": "done",
            })
            # Completed task floats to the top of its own service.
            task._assetz_realign_done_to_top()
        return {"type": "ir.actions.act_window_close"}
