from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetzJob(models.Model):
    """Job (ticket) executed by a technician to fulfil one order line."""

    _name = "assetz.job"
    _description = "Assetz Job"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_date desc, id desc"

    name = fields.Char(
        string="Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    order_id = fields.Many2one(
        "assetz.order",
        string="Order",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    order_line_id = fields.Many2one(
        "assetz.order.line",
        string="Order Line",
        ondelete="set null",
    )
    asset_id = fields.Many2one(
        "assetz.asset",
        string="Asset",
        required=True,
        tracking=True,
    )

    job_type = fields.Selection(
        selection=[
            ("service", "Service"),
            ("rental", "Rental"),
        ],
        string="Job Type",
        required=True,
        default="service",
        tracking=True,
    )

    technician_id = fields.Many2one(
        "hr.employee",
        string="Technician",
        tracking=True,
    )
    team_id = fields.Many2one(
        "assetz.maintenance.team",
        string="Team",
        tracking=True,
    )

    priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        string="Priority",
        default="1",
        tracking=True,
    )

    scheduled_date = fields.Datetime(string="Scheduled", tracking=True)
    actual_start = fields.Datetime(string="Started", readonly=True, copy=False)
    actual_end = fields.Datetime(string="Finished", readonly=True, copy=False)
    duration_hours = fields.Float(
        string="Duration (h)",
        compute="_compute_duration_hours",
        store=True,
    )

    description = fields.Text(string="Description / Issue Reported")
    work_done = fields.Text(string="Work Done")

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("assigned", "Assigned"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    company_id = fields.Many2one(
        related="order_id.company_id",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        readonly=True,
    )

    @api.depends("actual_start", "actual_end")
    def _compute_duration_hours(self):
        for job in self:
            if job.actual_start and job.actual_end:
                delta = job.actual_end - job.actual_start
                job.duration_hours = delta.total_seconds() / 3600.0
            else:
                job.duration_hours = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("assetz.job") or "New"
        return super().create(vals_list)

    def action_assign(self):
        for job in self:
            if not job.technician_id and not job.team_id:
                raise UserError("Assign a technician or a team before moving to Assigned.")
            job.state = "assigned"

    def action_start(self):
        for job in self:
            if job.state not in ("draft", "assigned"):
                raise UserError("Job can only be started from Draft or Assigned.")
            job.write({"state": "in_progress", "actual_start": fields.Datetime.now()})

    def action_done(self):
        for job in self:
            if job.state != "in_progress":
                raise UserError("Only in-progress jobs can be completed.")
            job.write({"state": "done", "actual_end": fields.Datetime.now()})

    def action_cancel(self):
        for job in self:
            job.state = "cancelled"

    def action_draft(self):
        for job in self:
            if job.state != "cancelled":
                raise UserError("Only cancelled jobs can be reset to draft.")
            job.state = "draft"
