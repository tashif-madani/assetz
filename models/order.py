from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AssetzOrder(models.Model):
    """Service or Rental order placed against one or more assets.

    Each order line spawns one job (`assetz.job`) when the order is confirmed —
    the job is the ticket a technician executes to fulfil the order.
    """

    _name = "assetz.order"
    _description = "Assetz Order (Service / Rental)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    order_type = fields.Selection(
        selection=[
            ("service", "Service Order"),
            ("rental", "Rental Order"),
        ],
        string="Order Type",
        required=True,
        default="service",
        tracking=True,
    )

    # Flexible recipient (mirrors assetz.issue.order)
    recipient_type = fields.Selection(
        selection=[
            ("employee", "Employee"),
            ("user", "System User"),
            ("partner", "Contact/Customer/Vendor"),
            ("department", "Department"),
            ("location", "Location/Site"),
            ("project", "Project"),
            ("cost_center", "Cost Center"),
            ("other", "Other (Free Text)"),
        ],
        string="Recipient Type",
        required=True,
        default="partner",
        tracking=True,
    )
    employee_id = fields.Many2one("hr.employee", string="Employee", tracking=True)
    user_id = fields.Many2one("res.users", string="System User", tracking=True)
    partner_id = fields.Many2one("res.partner", string="Contact", tracking=True)
    department_id = fields.Many2one("hr.department", string="Department", tracking=True)
    location_id = fields.Many2one("assetz.location", string="Location", tracking=True)
    project_name = fields.Char(string="Project Name", tracking=True)
    cost_center = fields.Char(string="Cost Center", tracking=True)
    recipient_name = fields.Char(string="Recipient Name", tracking=True)
    recipient_display = fields.Char(
        string="Recipient",
        compute="_compute_recipient_display",
        store=True,
    )

    # Dates
    date_order = fields.Date(
        string="Order Date",
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    date_start = fields.Date(string="Start Date", tracking=True)
    date_end = fields.Date(string="End Date", tracking=True)

    # Service-specific
    service_type = fields.Selection(
        selection=[
            ("installation", "Installation"),
            ("repair", "Repair"),
            ("inspection", "Inspection"),
            ("other", "Other"),
        ],
        string="Service Type",
        default="repair",
        tracking=True,
    )

    # Rental-specific
    rental_period = fields.Selection(
        selection=[
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
        ],
        string="Rental Period",
        default="daily",
        tracking=True,
    )
    rental_rate = fields.Monetary(
        string="Rental Rate",
        currency_field="currency_id",
        tracking=True,
        help="Rate per period unit (per day/week/month).",
    )
    total_rental_cost = fields.Monetary(
        string="Total Rental Cost",
        currency_field="currency_id",
        compute="_compute_total_rental_cost",
        store=True,
    )

    line_ids = fields.One2many(
        comodel_name="assetz.order.line",
        inverse_name="order_id",
        string="Lines",
        copy=True,
    )
    job_ids = fields.One2many(
        comodel_name="assetz.job",
        inverse_name="order_id",
        string="Jobs",
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    notes = fields.Text(string="Notes")

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    # Counts (for stat boxes)
    asset_count = fields.Integer(compute="_compute_counts")
    job_count = fields.Integer(compute="_compute_counts")
    job_done_count = fields.Integer(compute="_compute_counts")

    @api.depends(
        "recipient_type",
        "employee_id",
        "user_id",
        "partner_id",
        "department_id",
        "location_id",
        "project_name",
        "cost_center",
        "recipient_name",
    )
    def _compute_recipient_display(self):
        for order in self:
            mapping = {
                "employee": order.employee_id.name,
                "user": order.user_id.name,
                "partner": order.partner_id.name,
                "department": order.department_id.name,
                "location": order.location_id.complete_name if order.location_id else False,
                "project": order.project_name,
                "cost_center": f"Cost Center: {order.cost_center}" if order.cost_center else False,
                "other": order.recipient_name,
            }
            order.recipient_display = mapping.get(order.recipient_type) or "Not Specified"

    @api.depends("line_ids", "job_ids", "job_ids.state")
    def _compute_counts(self):
        for order in self:
            order.asset_count = len(order.line_ids)
            order.job_count = len(order.job_ids)
            order.job_done_count = len(order.job_ids.filtered(lambda j: j.state == "done"))

    @api.depends("order_type", "rental_rate", "rental_period", "date_start", "date_end")
    def _compute_total_rental_cost(self):
        for order in self:
            if order.order_type != "rental" or not (order.date_start and order.date_end and order.rental_rate):
                order.total_rental_cost = 0.0
                continue
            days = max((order.date_end - order.date_start).days, 0)
            if order.rental_period == "daily":
                units = days
            elif order.rental_period == "weekly":
                units = days / 7.0
            else:
                units = days / 30.0
            order.total_rental_cost = units * order.rental_rate

    @api.constrains("order_type", "date_start", "date_end")
    def _check_rental_dates(self):
        for order in self:
            if order.order_type != "rental":
                continue
            if not (order.date_start and order.date_end):
                raise ValidationError("Rental orders must have both a Start Date and an End Date.")
            if order.date_end < order.date_start:
                raise ValidationError("Rental End Date cannot be before Start Date.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                seq_code = (
                    "assetz.order.rental"
                    if vals.get("order_type") == "rental"
                    else "assetz.order.service"
                )
                vals["name"] = self.env["ir.sequence"].next_by_code(seq_code) or "New"
        return super().create(vals_list)

    def _create_jobs_for_lines(self):
        Job = self.env["assetz.job"]
        for order in self:
            for line in order.line_ids:
                if line.job_id:
                    continue
                job = Job.create({
                    "order_id": order.id,
                    "order_line_id": line.id,
                    "asset_id": line.asset_id.id,
                    "job_type": order.order_type,
                    "scheduled_date": order.date_start or order.date_order,
                    "description": line.description or order.notes or "",
                })
                line.job_id = job.id

    def action_confirm(self):
        for order in self:
            if not order.line_ids:
                raise UserError("Please add at least one line before confirming.")
            order._create_jobs_for_lines()
            order.state = "confirmed"

    def action_start(self):
        for order in self:
            if order.state != "confirmed":
                raise UserError("Only confirmed orders can be started.")
            order.state = "in_progress"

    def action_done(self):
        for order in self:
            open_jobs = order.job_ids.filtered(lambda j: j.state not in ("done", "cancelled"))
            if open_jobs:
                raise UserError(
                    "Cannot mark the order as done — the following jobs are still open: %s"
                    % ", ".join(open_jobs.mapped("name"))
                )
            order.state = "done"

    def action_cancel(self):
        for order in self:
            order.job_ids.filtered(lambda j: j.state != "done").write({"state": "cancelled"})
            order.state = "cancelled"

    def action_draft(self):
        for order in self:
            if order.state != "cancelled":
                raise UserError("Only cancelled orders can be reset to draft.")
            order.state = "draft"

    def action_view_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Jobs - {self.name}",
            "res_model": "assetz.job",
            "view_mode": "list,form,kanban",
            "domain": [("order_id", "=", self.id)],
            "context": {"default_order_id": self.id},
        }


class AssetzOrderLine(models.Model):
    _name = "assetz.order.line"
    _description = "Assetz Order Line"

    order_id = fields.Many2one(
        "assetz.order",
        string="Order",
        required=True,
        ondelete="cascade",
    )
    asset_id = fields.Many2one(
        "assetz.asset",
        string="Asset",
        required=True,
    )
    description = fields.Char(string="Description")
    quantity = fields.Float(string="Quantity", default=1.0)
    job_id = fields.Many2one(
        "assetz.job",
        string="Job",
        readonly=True,
        copy=False,
    )
    job_state = fields.Selection(related="job_id.state", string="Job Status", readonly=True)
    company_id = fields.Many2one(related="order_id.company_id", store=True)
